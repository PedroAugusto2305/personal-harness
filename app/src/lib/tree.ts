// Lista de caminhos → árvore de pastas para o explorador.

export interface TreeNode {
  name: string;
  path: string;
  dir: boolean;
  children: TreeNode[];
}

export function buildTree(paths: string[]): TreeNode {
  const root: TreeNode = { name: "", path: "", dir: true, children: [] };
  const dirs = new Map<string, TreeNode>([["", root]]);
  for (const path of paths) {
    const parts = path.split("/");
    let parent = root;
    for (let i = 0; i < parts.length; i++) {
      const sub = parts.slice(0, i + 1).join("/");
      const last = i === parts.length - 1;
      if (last) {
        parent.children.push({ name: parts[i], path: sub, dir: false, children: [] });
      } else {
        let dir = dirs.get(sub);
        if (!dir) {
          dir = { name: parts[i], path: sub, dir: true, children: [] };
          dirs.set(sub, dir);
          parent.children.push(dir);
        }
        parent = dir;
      }
    }
  }
  const sort = (node: TreeNode) => {
    node.children.sort((a, b) => (a.dir === b.dir ? a.name.localeCompare(b.name) : a.dir ? -1 : 1));
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

const IMAGE = /\.(png|jpe?g|gif|webp|svg|ico|bmp|avif)$/i;
const AUDIO = /\.(mp3|wav|m4a|aac|ogg|flac)$/i;
const VIDEO = /\.(mp4|mov|webm|m4v)$/i;

export type ViewerKind = "image" | "pdf" | "markdown" | "audio" | "video" | "html" | "csv" | "text";

export function viewerFor(path: string): ViewerKind {
  if (IMAGE.test(path)) return "image";
  if (/\.pdf$/i.test(path)) return "pdf";
  if (/\.(md|markdown|mdx)$/i.test(path)) return "markdown";
  if (AUDIO.test(path)) return "audio";
  if (VIDEO.test(path)) return "video";
  if (/\.html?$/i.test(path)) return "html";
  if (/\.(csv|tsv)$/i.test(path)) return "csv";
  return "text";
}

export function baseName(path: string): string {
  return path.split("/").pop() || path;
}
