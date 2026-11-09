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
  var FORWARD = { k: 1, p: 1, d: 1, l: 1, r: 1, "[": 1, "]": 1, ",": 1, "=": 1, "-": 1, "0": 1, "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1, "8": 1, "9": 1 };
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

  // --- agente (v0.9.8): o navegador pelo MCP, com o cursor do agente à vista --------
  // A MÊTIS chama window.__metis.agent(ação, args) e recebe JSON: {ok, v}, {ok:false, e} ou
  // {pendente: id} (ação com o cursor andando antes), lido depois por __metis.result(id).
  // Console e rede são guardados desde o começo da página (o script entra antes dela).
  var LIMIT = 300;
  var logs = [];
  var requests = [];
  var remember = function (list, item) {
    list.push(item);
    if (list.length > LIMIT) list.splice(0, list.length - LIMIT);
  };
  var msg = function (e) {
    return e && e.message ? e.message : String(e);
  };
  var absolute = function (url) {
    try {
      return new URL(String(url), location.href).href;
    } catch (e) {
      return String(url);
    }
  };
  var asText = function (value) {
    try {
      if (typeof value === "string") return value;
      if (value instanceof Error) return value.stack || String(value);
      return JSON.stringify(value);
    } catch (e) {
      return String(value);
    }
  };
  ["log", "info", "warn", "error", "debug"].forEach(function (level) {
    var original = console[level];
    if (typeof original !== "function") return;
    console[level] = function () {
      try {
        remember(logs, { nivel: level, texto: Array.prototype.map.call(arguments, asText).join(" ").slice(0, 2000), quando: Date.now() });
      } catch (e) {}
      return original.apply(this, arguments);
    };
  });
  window.addEventListener("error", function (e) {
    remember(logs, { nivel: "error", texto: (e.message || "erro") + (e.filename ? " (" + e.filename + ":" + e.lineno + ")" : ""), quando: Date.now() });
  });
  window.addEventListener("unhandledrejection", function (e) {
    remember(logs, { nivel: "error", texto: "promessa recusada: " + asText(e.reason).slice(0, 2000), quando: Date.now() });
  });
  if (window.fetch) {
    var realFetch = window.fetch;
    window.fetch = function (input, init) {
      var started = Date.now();
      var entry = {
        metodo: String((init && init.method) || (input && input.method) || "GET").toUpperCase(),
        url: absolute((input && input.url) || input),
        status: null,
        ms: null,
        tipo: "fetch",
        quando: Date.now(),
      };
      remember(requests, entry);
      return realFetch.apply(this, arguments).then(
        function (res) {
          entry.status = res.status;
          entry.ms = Date.now() - started;
          return res;
        },
        function (err) {
          entry.erro = msg(err);
          entry.ms = Date.now() - started;
          throw err;
        }
      );
    };
  }
  if (window.XMLHttpRequest) {
    var xhrOpen = XMLHttpRequest.prototype.open;
    var xhrSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__metisEntry = { metodo: String(method || "GET").toUpperCase(), url: absolute(url), status: null, ms: null, tipo: "xhr", quando: Date.now() };
      return xhrOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
      var entry = this.__metisEntry;
      var started = Date.now();
      if (entry) {
        remember(requests, entry);
        this.addEventListener("loadend", function () {
          entry.status = this.status || null;
          entry.ms = Date.now() - started;
          if (!this.status) entry.erro = "sem resposta";
        });
      }
      return xhrSend.apply(this, arguments);
    };
  }

  var clean = function (value, max) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, max || 80);
  };
  var INTERACTIVE =
    'a[href],button,input,select,textarea,summary,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="tab"],' +
    '[role="menuitem"],[role="option"],[role="switch"],[role="textbox"],[role="searchbox"],[role="combobox"],[contenteditable=""],[contenteditable="true"]';

  function kindOf(el) {
    var role = (el.getAttribute("role") || "").toLowerCase();
    var tag = el.tagName;
    if (tag === "INPUT") {
      var type = (el.type || "text").toLowerCase();
      if (type === "hidden") return null;
      if (type === "checkbox" || role === "switch") return "caixa";
      if (type === "radio") return "opção";
      if (/^(submit|button|reset|image)$/.test(type)) return "botão";
      if (type === "file") return "arquivo";
      if (type === "range") return "controle";
      return "campo";
    }
    if (tag === "SELECT" || role === "listbox") return "lista";
    if (tag === "TEXTAREA" || role === "textbox" || role === "searchbox" || role === "combobox") return "campo";
    if (role === "checkbox" || role === "switch") return "caixa";
    if (role === "radio") return "opção";
    if (role === "tab") return "aba";
    if (role === "menuitem" || role === "option") return "item";
    if (role === "button" || tag === "BUTTON" || tag === "SUMMARY") return "botão";
    if (role === "link" || (tag === "A" && el.hasAttribute("href"))) return "link";
    if (el.isContentEditable && !(el.parentElement && el.parentElement.isContentEditable)) return "campo";
    return null;
  }

  function nameOf(el) {
    var aria = el.getAttribute("aria-label");
    if (aria) return clean(aria);
    var by = el.getAttribute("aria-labelledby");
    if (by) {
      var joined = clean(
        by
          .split(/\s+/)
          .map(function (id) {
            var n = document.getElementById(id);
            return n ? n.innerText || n.textContent : "";
          })
          .join(" ")
      );
      if (joined) return joined;
    }
    if (el.labels && el.labels.length) {
      var label = clean(el.labels[0].innerText || el.labels[0].textContent);
      if (label) return label;
    }
    if (el.tagName === "IMG") return clean(el.alt || el.title);
    if (el.tagName === "INPUT" && /^(submit|button|reset)$/i.test(el.type)) return clean(el.value);
    if (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA" && el.tagName !== "SELECT") {
      var text = clean(el.innerText || el.textContent);
      if (text) return text;
      var img = el.querySelector && el.querySelector("img[alt]");
      if (img && img.alt) return clean(img.alt);
    }
    return clean(el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("name") || "");
  }

  function shown(el) {
    var style = getComputedStyle(el);
    if (style.display === "contents") return true;
    if (!el.getClientRects().length) return false;
    return style.visibility !== "hidden" && style.visibility !== "collapse";
  }

  function short(el) {
    var kind = kindOf(el);
    var name = nameOf(el);
    return (kind || el.tagName.toLowerCase()) + (name ? ' "' + name + '"' : "");
  }

  function where(href) {
    try {
      var u = new URL(href, location.href);
      return u.origin === location.origin ? u.pathname + u.search + u.hash : u.href;
    } catch (e) {
      return href;
    }
  }

  function line(el, ref, kind) {
    var out = "[" + ref + "] " + kind;
    var name = nameOf(el);
    if (name) out += ' "' + name + '"';
    if (kind === "link") out += " → " + clean(where(el.getAttribute("href")), 120);
    if (kind === "campo") {
      var type = (el.type || "").toLowerCase();
      if (type && type !== "text" && el.tagName === "INPUT") out += " (" + type + ")";
      var value = el.isContentEditable ? el.innerText : el.value;
      if (value) out += ' = "' + (type === "password" ? "••••" : clean(value, 120)) + '"';
      else if (el.placeholder && el.placeholder !== name) out += ' vazio, dica "' + clean(el.placeholder) + '"';
    }
    if (kind === "caixa" || kind === "opção") {
      var on = el.checked != null ? el.checked : el.getAttribute("aria-checked") === "true";
      out += on ? " [x]" : " [ ]";
    }
    if (kind === "lista" && el.tagName === "SELECT") {
      var chosen = el.options[el.selectedIndex];
      if (chosen) out += ' = "' + clean(chosen.text) + '"';
      var names = Array.prototype.slice.call(el.options, 0, 8).map(function (o) {
        return clean(o.text, 40);
      });
      out += " (opções: " + names.join(", ") + (el.options.length > 8 ? ", …" : "") + ")";
    }
    if (el.disabled || el.getAttribute("aria-disabled") === "true") out += " (desativado)";
    if (el.getAttribute("aria-expanded")) out += el.getAttribute("aria-expanded") === "true" ? " (aberto)" : " (fechado)";
    var r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) out += " (fora da tela)";
    return out;
  }

  /** O texto da página com uma ref [eN] em cada coisa clicável ou editável. */
  function snapshot() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-metis-ref]"), function (n) {
      n.removeAttribute("data-metis-ref");
    });
    var lines = [];
    var size = 0;
    var cut = 0;
    var count = 0;
    var MAX = 30000;
    var push = function (text) {
      if (size + text.length > MAX) {
        cut++;
        return;
      }
      lines.push(text);
      size += text.length + 1;
    };
    var walk = function (el) {
      if (!el || el.nodeType !== 1 || el.hasAttribute("data-metis")) return;
      var tag = el.tagName;
      if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|HEAD|META|LINK|svg|SVG)$/.test(tag)) return;
      if (!shown(el)) return;
      var kind = kindOf(el);
      if (kind) {
        count++;
        var ref = "e" + count;
        el.setAttribute("data-metis-ref", ref);
        push(line(el, ref, kind));
        if (kind !== "lista" || el.tagName === "SELECT") return;
      }
      if (/^H[1-6]$/.test(tag)) {
        var heading = clean(el.innerText || el.textContent, 160);
        if (heading) push(new Array(Number(tag[1]) + 1).join("#") + " " + heading);
        return;
      }
      if (tag === "IMG") {
        if (el.alt) push('imagem "' + clean(el.alt) + '"');
        return;
      }
      if (tag === "IFRAME") {
        push("(quadro: " + clean(el.getAttribute("src") || "sem endereço", 120) + ")");
        return;
      }
      // Bloco de texto sem nada clicável dentro: uma linha só.
      var display = getComputedStyle(el).display;
      if (display !== "inline" && display !== "contents" && !el.querySelector(INTERACTIVE) && !el.querySelector("h1,h2,h3,h4,h5,h6,img[alt]")) {
        var text = clean(el.innerText || "", 300);
        if (text) push(text);
        return;
      }
      var own = "";
      for (var child = el.firstChild; child; child = child.nextSibling) {
        if (child.nodeType === 3) own += child.nodeValue;
      }
      own = clean(own, 300);
      if (own) push(own);
      for (var next = el.firstElementChild; next; next = next.nextElementSibling) walk(next);
      if (el.shadowRoot) for (var inner = el.shadowRoot.firstElementChild; inner; inner = inner.nextElementSibling) walk(inner);
    };
    walk(document.body);
    var scroller = document.scrollingElement || document.documentElement;
    var head =
      "Rolagem: " + Math.round(scroller.scrollTop) + " de " + Math.max(0, Math.round(scroller.scrollHeight - window.innerHeight)) + " px (tela de " + window.innerHeight + " px)";
    if (cut) lines.push("(cortado: " + cut + " linhas a mais; role a página e leia de novo)");
    return head + "\n\n" + lines.join("\n");
  }

  function find(args) {
    if (args.ref) {
      var ref = String(args.ref).replace(/[^\w-]/g, "");
      var byRef = document.querySelector('[data-metis-ref="' + ref + '"]');
      if (!byRef) throw new Error("a ref " + ref + " não existe mais: leia a página de novo (navegador_ler)");
      return byRef;
    }
    if (args.seletor) {
      var bySelector = document.querySelector(args.seletor);
      if (!bySelector) throw new Error("nada casa com o seletor " + args.seletor);
      return bySelector;
    }
    if (args.texto) {
      var want = clean(args.texto, 200).toLowerCase();
      var candidates = Array.prototype.filter.call(document.querySelectorAll(INTERACTIVE + ",label"), shown);
      var exact = candidates.filter(function (el) {
        return nameOf(el).toLowerCase() === want;
      });
      var loose = candidates.filter(function (el) {
        return nameOf(el).toLowerCase().indexOf(want) >= 0;
      });
      var found = exact[0] || loose[0];
      if (!found) throw new Error('nada clicável com o texto "' + args.texto + '"');
      return found;
    }
    throw new Error("diga a ref (de navegador_ler), um seletor CSS ou o texto");
  }

  // O cursor do agente: uma seta com o rótulo "agente" que anda até o alvo antes da ação.
  var arrow = null;
  var arrowTimer = 0;
  var arrowAt = null;
  function cursorTo(x, y, click) {
    var moving = "transform 220ms cubic-bezier(.2,.7,.2,1), opacity 200ms";
    if (!arrow) {
      arrow = document.createElement("div");
      arrow.setAttribute("data-metis", "");
      arrow.style.cssText = "position:fixed;z-index:2147483647;pointer-events:none;left:0;top:0;opacity:0;will-change:transform;transition:" + moving;
      arrow.innerHTML =
        '<svg width="22" height="22" viewBox="0 0 24 24" style="display:block"><path d="M4 3l7.5 17 2.2-6.8L20.5 11z" fill="#82a0ff" stroke="#191a21" stroke-width="1.6" stroke-linejoin="round"/></svg>' +
        '<span style="position:absolute;left:18px;top:17px;background:#82a0ff;color:#191a21;font:600 10px/16px -apple-system,system-ui,sans-serif;padding:0 6px;border-radius:5px;white-space:nowrap">agente</span>';
      document.documentElement.appendChild(arrow);
    }
    if (!arrowAt) {
      arrow.style.transition = "none";
      arrow.style.transform = "translate(" + Math.round(window.innerWidth / 2) + "px," + Math.round(window.innerHeight / 2) + "px)";
      void arrow.offsetWidth;
      arrow.style.transition = moving;
    }
    arrow.style.opacity = "1";
    arrow.style.transform = "translate(" + Math.round(x - 4) + "px," + Math.round(y - 3) + "px)";
    arrowAt = { x: x, y: y };
    if (click) setTimeout(function () { ripple(x, y); }, 220);
    clearTimeout(arrowTimer);
    arrowTimer = setTimeout(function () {
      if (arrow) arrow.style.opacity = "0";
    }, 6000);
  }
  function ripple(x, y) {
    var ring = document.createElement("div");
    ring.setAttribute("data-metis", "");
    ring.style.cssText =
      "position:fixed;z-index:2147483646;pointer-events:none;left:" + (x - 14) + "px;top:" + (y - 14) + "px;width:28px;height:28px;" +
      "border-radius:50%;border:2px solid #82a0ff;opacity:.9;transform:scale(.4);transition:transform 380ms ease-out,opacity 380ms ease-out";
    document.documentElement.appendChild(ring);
    void ring.offsetWidth;
    ring.style.transform = "scale(1.5)";
    ring.style.opacity = "0";
    setTimeout(function () { ring.remove(); }, 420);
  }

  function aim(el) {
    var r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight || r.left < 0 || r.right > window.innerWidth) {
      el.scrollIntoView({ block: "center", inline: "center" });
      r = el.getBoundingClientRect();
    }
    return { x: Math.round(r.left + Math.min(r.width / 2, 40)), y: Math.round(r.top + r.height / 2) };
  }
  function mouse(el, type, p) {
    el.dispatchEvent(
      new MouseEvent(type, { bubbles: true, cancelable: true, composed: true, clientX: p.x, clientY: p.y, view: window, button: 0, buttons: /down$/.test(type) ? 1 : 0 })
    );
  }
  function pointerEvent(el, type, p) {
    if (!window.PointerEvent) return;
    el.dispatchEvent(
      new PointerEvent(type, { bubbles: true, cancelable: true, composed: true, clientX: p.x, clientY: p.y, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0, buttons: /down$/.test(type) ? 1 : 0 })
    );
  }
  function hoverAt(el, p) {
    pointerEvent(el, "pointerover", p);
    mouse(el, "mouseover", p);
    el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: false, clientX: p.x, clientY: p.y }));
    pointerEvent(el, "pointermove", p);
    mouse(el, "mousemove", p);
  }
  function clickAt(el, p) {
    hoverAt(el, p);
    pointerEvent(el, "pointerdown", p);
    mouse(el, "mousedown", p);
    if (el.focus) el.focus({ preventScroll: true });
    pointerEvent(el, "pointerup", p);
    mouse(el, "mouseup", p);
    el.click();
  }

  var KEYS = {
    Enter: ["Enter", 13], Escape: ["Escape", 27], Tab: ["Tab", 9], Backspace: ["Backspace", 8], Delete: ["Delete", 46],
    ArrowDown: ["ArrowDown", 40], ArrowUp: ["ArrowUp", 38], ArrowLeft: ["ArrowLeft", 37], ArrowRight: ["ArrowRight", 39],
    Space: [" ", 32], Home: ["Home", 36], End: ["End", 35], PageDown: ["PageDown", 34], PageUp: ["PageUp", 33],
  };
  function focusables() {
    return Array.prototype.filter.call(
      document.querySelectorAll('a[href],button,input:not([type="hidden"]),select,textarea,[tabindex]:not([tabindex="-1"]),[contenteditable="true"]'),
      function (el) {
        return shown(el) && !el.disabled;
      }
    );
  }
  function press(el, combo) {
    var parts = String(combo).split("+");
    var name = parts.pop();
    var shift = parts.indexOf("Shift") >= 0;
    var k = KEYS[name] || [name, name.length === 1 ? name.toUpperCase().charCodeAt(0) : 0];
    var key = k[0];
    var init = {
      key: key, code: name === "Space" ? "Space" : key.length === 1 ? "Key" + key.toUpperCase() : key, keyCode: k[1], which: k[1],
      shiftKey: shift, ctrlKey: parts.indexOf("Control") >= 0, altKey: parts.indexOf("Alt") >= 0, metaKey: parts.indexOf("Meta") >= 0,
      bubbles: true, cancelable: true, composed: true,
    };
    var go = el.dispatchEvent(new KeyboardEvent("keydown", init));
    if (key.length === 1 || key === "Enter") el.dispatchEvent(new KeyboardEvent("keypress", init));
    if (go) {
      if (key === "Enter" && el.tagName === "INPUT" && el.form) {
        if (el.form.requestSubmit) el.form.requestSubmit();
        else el.form.submit();
      } else if (key === "Enter" && (el.tagName === "A" || el.tagName === "BUTTON")) el.click();
      else if (key === " " && (el.tagName === "BUTTON" || el.type === "checkbox" || el.type === "radio")) el.click();
      else if (key === "Tab") {
        var list = focusables();
        var at = list.indexOf(el);
        var target = list[(at + (shift ? -1 : 1) + list.length) % list.length];
        if (target) target.focus();
      }
    }
    el.dispatchEvent(new KeyboardEvent("keyup", init));
  }

  function setValue(el, value) {
    var proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    var descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) descriptor.set.call(el, value);
    else el.value = value;
  }

  // Ação com o cursor andando: a resposta sai depois, por __metis.result(id).
  var results = {};
  var seq = 0;
  function later(work, delay) {
    var id = "p" + ++seq;
    results[id] = null;
    setTimeout(function () {
      try {
        var value = work();
        if (value && typeof value.then === "function") {
          value.then(
            function (v) { results[id] = { ok: true, v: safe(v) }; },
            function (e) { results[id] = { ok: false, e: msg(e) }; }
          );
        } else results[id] = { ok: true, v: value };
      } catch (e) {
        results[id] = { ok: false, e: msg(e) };
      }
    }, delay || 0);
    return { pendente: id };
  }
  function result(id) {
    var r = results[id];
    if (r === undefined) return JSON.stringify({ ok: false, perdido: true, e: "a página mudou antes da resposta" });
    if (r === null) return JSON.stringify({ pendente: id });
    delete results[id];
    return JSON.stringify(r);
  }

  /** Valor de navegador_js em JSON, sem ciclos nem nós do DOM crus. */
  function safe(value) {
    var seen = [];
    try {
      var text = JSON.stringify(value, function (_k, v) {
        if (v && typeof v === "object") {
          if (v.nodeType === 1) return "<" + short(v) + ">";
          if (seen.indexOf(v) >= 0) return "[ciclo]";
          seen.push(v);
        }
        if (typeof v === "function") return "[função]";
        if (v === undefined) return null;
        return v;
      });
      if (text === undefined) return null;
      return text.length > 20000 ? text.slice(0, 20000) + "…" : JSON.parse(text);
    } catch (e) {
      return String(value);
    }
  }

  function scrollable() {
    var best = null;
    var area = 0;
    Array.prototype.forEach.call(document.querySelectorAll("*"), function (el) {
      if (el.scrollHeight <= el.clientHeight + 10) return;
      var overflow = getComputedStyle(el).overflowY;
      if (overflow !== "auto" && overflow !== "scroll") return;
      var size = el.clientWidth * el.clientHeight;
      if (size > area) {
        area = size;
        best = el;
      }
    });
    return best;
  }

  var ACTIONS = {
    ler: function () {
      return snapshot();
    },
    clicar: function (a) {
      var el = find(a);
      var what = short(el);
      var p = aim(el);
      cursorTo(p.x, p.y, true);
      return later(function () {
        clickAt(el, p);
        return "clicou em " + what;
      }, 240);
    },
    digitar: function (a) {
      // Aqui o texto é o que vai ser digitado, não o jeito de achar o campo.
      var el = find({ ref: a.ref, seletor: a.seletor });
      var what = short(el);
      var p = aim(el);
      cursorTo(p.x, p.y, true);
      return later(function () {
        hoverAt(el, p);
        if (el.focus) el.focus({ preventScroll: true });
        var text = String(a.texto == null ? "" : a.texto);
        if (el.isContentEditable) {
          if (a.limpar !== false) document.execCommand("selectAll");
          document.execCommand("insertText", false, text);
        } else if ("value" in el && el.tagName !== "BUTTON") {
          setValue(el, (a.limpar === false ? el.value : "") + text);
          el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        } else throw new Error(what + " não recebe texto");
        if (a.enviar) press(el, "Enter");
        return "digitou em " + what + (a.enviar ? " e mandou (Enter)" : "");
      }, 240);
    },
    tecla: function (a) {
      var el = document.activeElement && document.activeElement !== document.documentElement ? document.activeElement : document.body;
      press(el, a.tecla || "Enter");
      return "apertou " + (a.tecla || "Enter") + " em " + short(el);
    },
    escolher: function (a) {
      var el = find({ ref: a.ref, seletor: a.seletor });
      if (el.tagName !== "SELECT") throw new Error(short(el) + " não é uma lista (select): abra com navegador_clicar e clique no item");
      var want = clean(a.valor, 200).toLowerCase();
      var options = Array.prototype.slice.call(el.options);
      var option =
        options.filter(function (o) { return o.value.toLowerCase() === want || clean(o.text, 200).toLowerCase() === want; })[0] ||
        options.filter(function (o) { return clean(o.text, 200).toLowerCase().indexOf(want) >= 0; })[0];
      if (!option) throw new Error('nenhuma opção "' + a.valor + '" (há: ' + options.slice(0, 12).map(function (o) { return clean(o.text, 30); }).join(", ") + ")");
      var p = aim(el);
      cursorTo(p.x, p.y, true);
      setValue(el, option.value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return 'escolheu "' + clean(option.text) + '" em ' + short(el);
    },
    passar: function (a) {
      var el = find(a);
      var what = short(el);
      var p = aim(el);
      cursorTo(p.x, p.y, false);
      return later(function () {
        hoverAt(el, p);
        return "passou o mouse em " + what;
      }, 240);
    },
    rolar: function (a) {
      if (a.ref || a.seletor) {
        var el = find(a);
        el.scrollIntoView({ block: "center" });
        return "rolou até " + short(el);
      }
      var dy = (Number(a.pixels) || Math.round(window.innerHeight * 0.8)) * (a.direcao === "cima" ? -1 : 1);
      var page = document.scrollingElement || document.documentElement;
      var before = page.scrollTop;
      window.scrollBy(0, dy);
      var box = page;
      if (page.scrollTop === before) {
        var inner = scrollable();
        if (inner) {
          inner.scrollBy(0, dy);
          box = inner;
        }
      }
      return "rolou " + (dy > 0 ? "para baixo" : "para cima") + "; agora em " + Math.round(box.scrollTop) + " de " + Math.max(0, Math.round(box.scrollHeight - box.clientHeight)) + " px";
    },
    achar: function (a) {
      if (a.seletor) {
        var el = document.querySelector(a.seletor);
        return { achou: !!(el && shown(el)) };
      }
      var want = clean(a.texto, 300).toLowerCase();
      return { achou: !!want && clean(document.body ? document.body.innerText : "", 1e7).toLowerCase().indexOf(want) >= 0 };
    },
    console: function (a) {
      var out = logs.slice(-150);
      if (a.limpar) logs.length = 0;
      return { entradas: out };
    },
    rede: function (a) {
      var seen = {};
      var list = requests.slice();
      list.forEach(function (r) { seen[r.url] = 1; });
      try {
        performance.getEntriesByType("resource").forEach(function (r) {
          if (seen[r.name] || r.initiatorType === "fetch" || r.initiatorType === "xmlhttprequest") return;
          list.push({
            metodo: "GET", url: r.name, status: r.responseStatus || null, ms: Math.round(r.duration), tipo: r.initiatorType,
            quando: Math.round(performance.timeOrigin + r.startTime),
          });
        });
      } catch (e) {}
      var want = clean(a.filtro, 200).toLowerCase();
      if (want) list = list.filter(function (r) { return r.url.toLowerCase().indexOf(want) >= 0; });
      list.sort(function (x, y) { return (x.quando || 0) - (y.quando || 0); });
      return { pedidos: list.slice(-150) };
    },
    js: function (a) {
      var value = (0, eval)(String(a.codigo || ""));
      if (value && typeof value.then === "function") return later(function () { return value; }, 0);
      return safe(value);
    },
  };

  function agent(name, args) {
    try {
      var run = ACTIONS[name];
      if (!run) throw new Error("ação desconhecida: " + name);
      var value = run(args || {});
      return JSON.stringify(value && value.pendente ? value : { ok: true, v: value });
    } catch (e) {
      return JSON.stringify({ ok: false, e: msg(e) });
    }
  }

  window.__metis = { design: setDesign, agent: agent, result: result };
})();
