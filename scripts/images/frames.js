const TAGLINE = "Find any Claude Code session by what was said in it.";
const INSTALL = "brew install alex-yanchenko/tap/ccsearch";
const REPO = "github.com/alex-yanchenko/ccsearch";

const element = (tag, className, children = []) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children);
  return node;
};

const screen = async (name) => {
  const capture = element("pre", "screen");
  capture.innerHTML = await fetch(`${name}.html`).then((response) => response.text());
  return capture;
};

const terminal = (title, body, className = "") =>
  element("div", `terminal ${className}`, [
    element("div", "bar", [
      element("span", "dot dot-red"),
      element("span", "dot dot-yellow"),
      element("span", "dot dot-green"),
      element("span", "bar-title", [title]),
    ]),
    element("div", "terminal-body", body),
  ]);

const prompt = (command) =>
  element("div", "prompt", [element("span", "prompt-path", ["~/code ❯ "]), command]);

const wordmark = () => element("div", "wordmark", ["ccsearch"]);

const scenes = {
  hero: async (stage) => {
    stage.append(
      element("header", "hero-head", [wordmark(), element("p", "tagline", [TAGLINE])]),
      terminal("ccsearch · type to search, Enter resumes", [await screen("browser")], "hero-terminal"),
    );
  },
  search: async (stage) => {
    stage.append(
      terminal("zsh", [prompt('ccsearch "rate limit"'), await screen("search")], "search-terminal"),
    );
  },
  social: async (stage) => {
    stage.append(
      element("section", "pitch", [
        wordmark(),
        element("p", "tagline", [TAGLINE]),
        element("code", "install", [INSTALL]),
        element("p", "repo", [REPO]),
      ]),
      terminal("ccsearch", [await screen("browser")], "social-terminal"),
    );
  },
};

const name = location.hash.slice(1);
const render = scenes[name];
document.body.classList.add(name);
render(document.getElementById("stage")).catch((error) => {
  document.body.replaceChildren(element("pre", "failure", [String(error)]));
});
