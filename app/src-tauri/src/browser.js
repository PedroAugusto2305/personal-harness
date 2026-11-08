// Injetado em cada página do navegador da MÊTIS. Duas tarefas:
// 1. Modo de design: realça o elemento sob o mouse e, no clique, manda à MÊTIS o HTML,
//    o estilo, o seletor e, quando dá, o componente e o arquivo de origem.
// 2. Atalhos: ⌘K, ⌘P, ⌘D… apertados dentro da página voltam para a MÊTIS.
// Fala com o app navegando para metis://…, que o app intercepta e cancela.
(function () {
  if (window.__metis || window.top !== window) return;

  var send = function (kind, data) {
    try {
      window.location.href = "metis://" + kind + "?d=" + encodeURIComponent(JSON.stringify(data || {}));
    } catch (e) {}
  };

  // --- atalhos -------------------------------------------------------------
  var FORWARD = { k: 1, p: 1, d: 1, l: 1, r: 1, "[": 1, "]": 1, ",": 1, "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1, "8": 1, "9": 1 };
  window.addEventListener(
    "keydown",
    function (e) {
      var key = (e.key || "").toLowerCase();
      var meta = e.metaKey && !e.ctrlKey && !e.altKey;
      var forward =
        (meta && !e.shiftKey && FORWARD[key]) ||
        (meta && e.shiftKey && (e.code === "KeyB" || e.code === "KeyM")) ||
        (e.ctrlKey && !e.metaKey && e.code === "Backquote") ||
        (design && e.key === "Escape");
      if (!forward) return;
      e.preventDefault();
      e.stopPropagation();
      if (design && e.key === "Escape") {
        setDesign(false);
        send("design-off", {});
        return;
      }
      send("key", { key: e.key, code: e.code, meta: e.metaKey, shift: e.shiftKey, ctrl: e.ctrlKey, alt: e.altKey });
    },
    true
  );

  // --- modo de design --------------------------------------------------------
  var design = false;
  var box = null;
  var tag = null;
  var current = null;

  function ensureOverlay() {
    if (box) return;
    box = document.createElement("div");
    box.setAttribute("data-metis", "");
    box.style.cssText =
      "position:fixed;z-index:2147483646;pointer-events:none;border:2px solid #82a0ff;background:rgba(130,160,255,.14);" +
      "border-radius:3px;transition:all 60ms ease-out;display:none;box-sizing:border-box";
    tag = document.createElement("div");
    tag.setAttribute("data-metis", "");
    tag.style.cssText =
      "position:fixed;z-index:2147483647;pointer-events:none;background:#191a21;color:#f8f8f2;padding:3px 7px;" +
      "border-radius:5px;font:11px/1.4 ui-monospace,Menlo,monospace;display:none;white-space:nowrap;max-width:60vw;" +
      "overflow:hidden;text-overflow:ellipsis;box-shadow:0 4px 14px rgba(0,0,0,.35)";
    document.documentElement.appendChild(box);
    document.documentElement.appendChild(tag);
  }

  function short(el) {
    var name = el.tagName.toLowerCase();
    if (el.id) name += "#" + el.id;
    var classes = (typeof el.className === "string" ? el.className : "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (classes.length) name += "." + classes.join(".");
    return name;
  }

  function selector(el) {
    var parts = [];
    for (var n = el; n && n.nodeType === 1 && n !== document.documentElement && parts.length < 6; n = n.parentElement) {
      if (n.id) {
        parts.unshift(n.tagName.toLowerCase() + "#" + n.id);
        break;
      }
      var part = n.tagName.toLowerCase();
      var parent = n.parentElement;
      if (parent) {
        var same = Array.prototype.filter.call(parent.children, function (c) {
          return c.tagName === n.tagName;
        });
        if (same.length > 1) part += ":nth-of-type(" + (same.indexOf(n) + 1) + ")";
      }
      parts.unshift(part);
    }
    return parts.join(" > ");
  }

  // Onde no código: atributos de ferramentas de inspeção, React, Svelte ou Vue.
  function source(el) {
    var found = { file: null, line: null, components: [] };
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      var attr =
        n.getAttribute("data-inspector-relative-path") ||
        n.getAttribute("data-source") ||
        n.getAttribute("data-loc") ||
        n.getAttribute("data-sourcefile");
      if (attr) {
        var m = /^(.*?)(?::(\d+))?(?::\d+)?$/.exec(attr);
        found.file = m ? m[1] : attr;
        found.line = (m && m[2]) || n.getAttribute("data-inspector-line") || n.getAttribute("data-sourceline");
        break;
      }
    }
    try {
      var key = Object.keys(el).find(function (k) {
        return k.indexOf("__reactFiber$") === 0 || k.indexOf("__reactInternalInstance$") === 0;
      });
      for (var f = key ? el[key] : null, guard = 0; f && guard < 60; f = f.return, guard++) {
        var type = f.type;
        var name = type && typeof type !== "string" ? type.displayName || type.name : null;
        if (name && found.components.length < 5 && found.components.indexOf(name) === -1) found.components.push(name);
        if (!found.file && f._debugSource) {
          found.file = f._debugSource.fileName;
          found.line = f._debugSource.lineNumber;
        }
        if (!found.file && f._debugStack && f._debugStack.stack) {
          var frames = String(f._debugStack.stack).match(/https?:\/\/[^\s)]+?:\d+:\d+/g) || [];
          for (var i = 0; i < frames.length; i++) {
            if (/node_modules|\/@vite|\/@react-refresh|react-dom|jsx-dev-runtime|chunk-/.test(frames[i])) continue;
            var fm = /^https?:\/\/[^/]+(\/[^?:]+)(?:\?[^:]*)?:(\d+):\d+$/.exec(frames[i]);
            if (fm) {
              found.file = fm[1].replace(/^\//, "");
              found.line = fm[2];
              found.approx = true;
              break;
            }
          }
        }
      }
    } catch (e) {}
    try {
      for (var s = el; s && !found.file; s = s.parentElement) {
        if (s.__svelte_meta && s.__svelte_meta.loc) {
          found.file = s.__svelte_meta.loc.file;
          found.line = s.__svelte_meta.loc.line + 1;
        }
      }
      for (var v = el; v && !found.file; v = v.parentElement) {
        var inst = v.__vueParentComponent;
        if (inst && inst.type && inst.type.__file) found.file = inst.type.__file;
      }
    } catch (e) {}
    return found;
  }

  var STYLE_KEYS = [
    "display", "position", "width", "height", "margin", "padding", "gap", "flex-direction", "justify-content", "align-items",
    "grid-template-columns", "font-family", "font-size", "font-weight", "line-height", "letter-spacing", "color",
    "background-color", "background-image", "border", "border-radius", "box-shadow", "opacity",
  ];
  var SKIP = { none: 1, normal: 1, auto: 1, "0px": 1, "rgba(0, 0, 0, 0)": 1, static: 1, "1": 1, "0px none rgb(0, 0, 0)": 1 };

  function styles(el) {
    var css = window.getComputedStyle(el);
    var out = [];
    STYLE_KEYS.forEach(function (k) {
      var v = css.getPropertyValue(k);
      if (v && !SKIP[v]) out.push(k + ": " + v);
    });
    return out;
  }

  function describe(el) {
    var rect = el.getBoundingClientRect();
    var html = el.outerHTML || "";
    var text = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
    return {
      url: location.href,
      title: document.title,
      selector: selector(el),
      element: short(el),
      text: text.slice(0, 200),
      html: html.length > 1500 ? html.slice(0, 1500) + "…" : html,
      styles: styles(el),
      size: Math.round(rect.width) + "×" + Math.round(rect.height),
      position: Math.round(rect.left) + "," + Math.round(rect.top),
      source: source(el),
    };
  }

  function highlight(el) {
    if (!el || el === current) return;
    current = el;
    var r = el.getBoundingClientRect();
    box.style.display = tag.style.display = "block";
    box.style.left = r.left + "px";
    box.style.top = r.top + "px";
    box.style.width = r.width + "px";
    box.style.height = r.height + "px";
    tag.textContent = short(el) + "  " + Math.round(r.width) + "×" + Math.round(r.height);
    tag.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 260)) + "px";
    tag.style.top = (r.top > 26 ? r.top - 24 : r.bottom + 4) + "px";
  }

  function target(e) {
    var el = e.target;
    return el && el.nodeType === 1 && !el.hasAttribute("data-metis") ? el : null;
  }

  function onMove(e) {
    var el = target(e);
    if (el) highlight(el);
  }

  function block(e) {
    e.preventDefault();
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
  }

  function onClick(e) {
    block(e);
    var el = target(e) || current;
    if (!el) return;
    box.style.borderColor = "#bd93f9";
    setTimeout(function () {
      if (box) box.style.borderColor = "#82a0ff";
    }, 300);
    send("pick", describe(el));
  }

  function setDesign(on) {
    design = !!on;
    var opts = { capture: true };
    if (design) {
      ensureOverlay();
      document.addEventListener("mousemove", onMove, true);
      ["click", "mousedown", "mouseup", "pointerdown", "pointerup", "auxclick", "dblclick", "submit"].forEach(function (t) {
        document.addEventListener(t, t === "click" ? onClick : block, opts);
      });
      document.documentElement.style.cursor = "crosshair";
    } else {
      document.removeEventListener("mousemove", onMove, true);
      ["click", "mousedown", "mouseup", "pointerdown", "pointerup", "auxclick", "dblclick", "submit"].forEach(function (t) {
        document.removeEventListener(t, t === "click" ? onClick : block, opts);
      });
      document.documentElement.style.cursor = "";
      if (box) box.style.display = tag.style.display = "none";
      current = null;
    }
  }

  window.__metis = { design: setDesign };
})();
