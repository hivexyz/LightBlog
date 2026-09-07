var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/client/index.ts
var index_exports = {};
__export(index_exports, {
  apply: () => apply,
  inject: () => inject
});
module.exports = __toCommonJS(index_exports);
var import_react = require("react");
var inject = ["slots", "sessions"];
var FETCH_BASE = "";
function apply(ctx) {
  ctx.slots.inject("shell.overlay", () => ctx.slots.register(
    { name: "shell.overlay", id: "paper-reader", label: "Paper Reader" },
    function PaperReaderPanel() {
      const sessions = ctx.sessions;
      const [open, setOpen] = (0, import_react.useState)(false);
      const [activeView, setActiveView] = (0, import_react.useState)("browser");
      const [currentDir, setCurrentDir] = (0, import_react.useState)("");
      const [files, setFiles] = (0, import_react.useState)([]);
      const [filePath, setFilePath] = (0, import_react.useState)("");
      const [fileLoading, setFileLoading] = (0, import_react.useState)(false);
      const [fileError, setFileError] = (0, import_react.useState)("");
      const [originalText, setOriginalText] = (0, import_react.useState)("");
      const [fileName, setFileName] = (0, import_react.useState)("");
      const [translation, setTranslation] = (0, import_react.useState)("");
      const [selectedText, setSelectedText] = (0, import_react.useState)("");
      const [translating, setTranslating] = (0, import_react.useState)(false);
      const [translationError, setTranslationError] = (0, import_react.useState)("");
      const [qaMessages, setQaMessages] = (0, import_react.useState)([]);
      const [qaInput, setQaInput] = (0, import_react.useState)("");
      const [qaLoading, setQaLoading] = (0, import_react.useState)(false);
      const [status, setStatus] = (0, import_react.useState)("");
      const [error, setError] = (0, import_react.useState)("");
      const [currentSession, setCurrentSession] = (0, import_react.useState)(getCurrentSession);
      const chatEndRef = (0, import_react.useRef)(null);
      function getCurrentSession() {
        const list = sessions.list.getSnapshot();
        const currentId = list.current;
        return currentId ? sessions.binding(currentId)?.session : void 0;
      }
      (0, import_react.useEffect)(() => {
        const updateCurrentSession = () => setCurrentSession(getCurrentSession());
        updateCurrentSession();
        const subscribe = sessions.list.subscribe;
        if (typeof subscribe !== "function") return void 0;
        return subscribe.call(sessions.list, updateCurrentSession);
      }, [sessions]);
      (0, import_react.useEffect)(() => {
        if (!currentSession) return;
        const face = currentSession.projections.faceOf("paperReader");
        const read = () => face.getSnapshot();
        const update = () => {
          const state = read();
          if (!state) return;
          if (state.translation) {
            setTranslation(state.translation);
            setTranslating(false);
            setStatus("");
            setError("");
          }
          if (state.qa.length > 0) {
            const last = state.qa[state.qa.length - 1];
            setQaMessages((prev) => {
              const lastUser = prev[prev.length - 1];
              if (lastUser && lastUser.role === "user" && lastUser.text === last.question) {
                if (prev.some((m) => m.role === "assistant" && m.text === last.answer)) return prev;
                return [...prev, { role: "assistant", text: last.answer }];
              }
              return prev;
            });
            setQaLoading(false);
            setStatus("");
            setError("");
          }
        };
        update();
        const off = face.subscribe(update);
        return off;
      }, [currentSession]);
      (0, import_react.useEffect)(() => {
        chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
      }, [qaMessages]);
      (0, import_react.useEffect)(() => {
        if (open && activeView === "browser") {
          loadFiles("");
        }
      }, [open, activeView]);
      const loadFiles = (0, import_react.useCallback)(async (dir) => {
        setFileLoading(true);
        setFileError("");
        try {
          const params = dir ? `?path=${encodeURIComponent(dir)}` : "";
          const res = await fetch(`${FETCH_BASE}/paper-reader/files${params}`);
          const data = await res.json();
          if (data.ok) {
            setFiles(data.items);
            setCurrentDir(data.path);
          } else {
            setFileError(data.error || "Failedto list files");
          }
        } catch (err) {
          setFileError(err instanceof Error ? err.message : String(err));
        } finally {
          setFileLoading(false);
        }
      }, []);
      const readFile = (0, import_react.useCallback)(async (path) => {
        setFileLoading(true);
        setFileError("");
        try {
          const res = await fetch(`${FETCH_BASE}/paper-reader/read?path=${encodeURIComponent(path)}`);
          const data = await res.json();
          if (data.ok) {
            setOriginalText(data.content);
            setFileName(data.name);
            setFilePath(path);
            setTranslation("");
            setSelectedText("");
            setActiveView("reader");
            await loadPaperViaSteer(data.content);
          } else {
            setFileError(data.error || "Failedto readfile");
          }
        } catch (err) {
          setFileError(err instanceof Error ? err.message : String(err));
        } finally {
          setFileLoading(false);
        }
      }, []);
      async function loadPaperViaSteer(text) {
        const session = getCurrentSession();
        if (!session) {
          setError("Noactive session. Please open or createa conversation first.");
          return;
        }
        setStatus("Loadingpaper into session...");
        try {
          const result = await session.prompt(
            [{ type: "text", text: `Call thepaper_load toolwith thistext:

${text.slice(0, 5e4)}` }],
            "steer"
          );
          if (!result.ok) {
            setError(result.error.message);
          } else {
            setStatus("Paper loaded. Readyfor translation andQ&A.");
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
      async function steer(prompt) {
        const session = getCurrentSession();
        setCurrentSession(session);
        if (!session) {
          setError("Noactive session. Please open or createa conversation first.");
          setStatus("");
          setTranslating(false);
          setQaLoading(false);
          return false;
        }
        try {
          const result = await session.prompt([{ type: "text", text: prompt }], "steer");
          if (!result.ok) {
            setError(result.error.message);
            setStatus("");
            setTranslating(false);
            setQaLoading(false);
            return false;
          }
          return true;
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
          setStatus("");
          setTranslating(false);
          setQaLoading(false);
          return false;
        }
      }
      async function handleTranslatePaper() {
        if (!originalText.trim()) {
          setError("Nopaper loaded. Please opena file first.");
          return;
        }
        setTranslating(true);
        setTranslation("");
        setStatus("Sending translationrequest...");
        setError("");
        await steer(
          `Callpaper_translate to translate the loadedpaper intoChinese.`
        );
      }
      async function handleTranslateSelection() {
        if (!selectedText.trim()) {
          setTranslationError("Please select some text first.");
          return;
        }
        setTranslating(true);
        setTranslation("");
        setTranslationError("");
        setStatus("Translating selectedtext...");
        const session = getCurrentSession();
        if (!session) {
          setError("No active session.");
          setTranslating(false);
          return;
        }
        try {
          const result = await session.prompt(
            [{ type: "text", text: `Translate the following text to Chinese. Output ONLY the translation,no explanationor commentary:

${selectedText}` }],
            "steer"
          );
          if (result.ok) {
            setStatus("Translation request sent.Check the conversation for the result.");
          } else {
            setError(result.error.message);
          }
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setTranslating(false);
        }
      }
      async function handleAsk() {
        if (!qaInput.trim()) return;
        const question = qaInput.trim();
        setQaMessages((prev) => [...prev, { role: "user", text: question }]);
        setQaInput("");
        setQaLoading(true);
        setStatus("Sending Q&A request...");
        setError("");
        const hasPaper = originalText.trim().length > 0;
        await steer(
          hasPaper ? `Callpaper_qa withthisquestion:${question}` : `Answer thisquestion: ${question}`
        );
      }
      function handleTextSelect() {
        const selection = window.getSelection();
        const text = selection?.toString().trim() || "";
        setSelectedText(text);
        if (text) {
          setTranslationError("");
        }
      }
      function renderFileBrowser() {
        return (0, import_react.createElement)(
          "div",
          {
            style: {
              display: "flex",
              flexDirection: "column",
              height: "100%",
              background: "var(--dsw-bg-secondary, #16213e)"
            }
          },
          (0, import_react.createElement)(
            "div",
            {
              style: {
                padding: "12px16px",
                fontWeight: 600,
                borderBottom: "1px solidvar(--dsw-border, #333)",
                color: "var(--dsw-text,#e0e0e0)",
                fontSize: 14,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between"
              }
            },
            (0, import_react.createElement)("span", null, "\u{1F4C1} Workspace Files"),
            (0, import_react.createElement)("button", {
              onClick: () => loadFiles(currentDir),
              style: {
                background: "transparent",
                border: "1pxsolid var(--dsw-border, #444)",
                color: "var(--dsw-text, #e0e0e0)",
                borderRadius: 4,
                padding: "4px8px",
                fontSize: 12,
                cursor: "pointer"
              }
            }, "\u21BB Refresh")
          ),
          fileError && (0, import_react.createElement)("div", {
            style: { padding: "8px12px", color: "#fca5a5", fontSize: 12, background: "rgba(127,29,29,0.25)" }
          }, fileError),
          fileLoading ? (0, import_react.createElement)("div", {
            style: { padding: 20, textAlign: "center", color: "var(--dsw-text-secondary,#888)" }
          }, "Loading...") : (0, import_react.createElement)(
            "div",
            {
              style: { flex: 1, overflow: "auto", padding: "4px0" }
            },
            // Parent directory navigation
            currentDir && currentDir !== "." && (0, import_react.createElement)("div", {
              onClick: () => {
                const parts = currentDir.split("/");
                parts.pop();
                loadFiles(parts.join("/") || "");
              },
              style: {
                padding: "8px16px",
                cursor: "pointer",
                color: "var(--dsw-accent, #4f46e5)",
                fontSize: 13,
                display: "flex",
                alignItems: "center",
                gap: 6,
                borderBottom: "1pxsolid var(--dsw-border, #222)"
              }
            }, "\u{1F4C2} .."),
            ...files.map(
              (entry, i) => (0, import_react.createElement)(
                "div",
                {
                  key: i,
                  onClick: () => {
                    if (entry.isDirectory) {
                      loadFiles(entry.path);
                    } else {
                      readFile(entry.path);
                    }
                  },
                  style: {
                    padding: "8px16px",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 13,
                    color: "var(--dsw-text, #e0e0e0)",
                    borderBottom: "1px solidvar(--dsw-border,#222)",
                    transition: "background0.15s"
                  },
                  onMouseEnter: (e) => {
                    e.currentTarget.style.background = "var(--dsw-hover, rgba(255,255,255,0.05))";
                  },
                  onMouseLeave: (e) => {
                    e.currentTarget.style.background = "transparent";
                  }
                },
                (0, import_react.createElement)("span", { style: { fontSize: 16 } }, entry.isDirectory ? "\u{1F4C1}" : "\u{1F4C4}"),
                (0, import_react.createElement)("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, entry.name),
                !entry.isDirectory && (0, import_react.createElement)("span", {
                  style: { fontSize: 11, color: "var(--dsw-text-secondary,#666)" }
                }, formatSize(entry.size))
              )
            ),
            files.length === 0 && !fileLoading && (0, import_react.createElement)("div", {
              style: { padding: 20, textAlign: "center", color: "var(--dsw-text-secondary,#888)", fontSize: 13 }
            }, "No filesfound")
          )
        );
      }
      function renderReader() {
        return (0, import_react.createElement)(
          "div",
          {
            style: {
              display: "flex",
              flexDirection: "row",
              height: "100%",
              flex: 1
            }
          },
          // Left: Originaltext
          (0, import_react.createElement)(
            "div",
            {
              style: {
                flex: 1,
                display: "flex",
                flexDirection: "column",
                borderRight: "1pxsolid var(--dsw-border, #333)",
                minWidth: 0
              }
            },
            (0, import_react.createElement)(
              "div",
              {
                style: {
                  padding: "10px16px",
                  fontWeight: 600,
                  borderBottom: "1px solidvar(--dsw-border, #333)",
                  color: "var(--dsw-text, #e0e0e0)",
                  fontSize: 13,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background: "var(--dsw-bg-secondary, #16213e)"
                }
              },
              (0, import_react.createElement)("span", null, `\u{1F4C4} ${fileName}`),
              (0, import_react.createElement)(
                "div",
                { style: { display: "flex", gap: 6 } },
                (0, import_react.createElement)("button", {
                  onClick: () => setActiveView("browser"),
                  style: {
                    background: "transparent",
                    border: "1pxsolid var(--dsw-border, #444)",
                    color: "var(--dsw-text, #e0e0e0)",
                    borderRadius: 4,
                    padding: "3px8px",
                    fontSize: 11,
                    cursor: "pointer"
                  }
                }, "\u2190Back"),
                (0, import_react.createElement)("button", {
                  onClick: handleTranslatePaper,
                  disabled: translating,
                  style: {
                    background: translating ? "#555" : "var(--dsw-accent,#4f46e5)",
                    border: "none",
                    color: "white",
                    borderRadius: 4,
                    padding: "3px10px",
                    fontSize: 11,
                    cursor: translating ? "not-allowed" : "pointer"
                  }
                }, translating ? "..." : "\u{1F310}Translate All")
              )
            ),
            (0, import_react.createElement)("div", {
              onMouseUp: handleTextSelect,
              style: {
                flex: 1,
                padding: 16,
                overflow: "auto",
                color: "var(--dsw-text,#e0e0e0)",
                fontSize: 14,
                lineHeight: 1.7,
                whiteSpace: "pre-wrap",
                fontFamily: "Georgia,serif",
                userSelect: "text"
              }
            }, originalText || (fileLoading ? "Loading..." : "")),
            selectedText && (0, import_react.createElement)(
              "div",
              {
                style: {
                  padding: "8px12px",
                  borderTop: "1pxsolid var(--dsw-border, #333)",
                  background: "var(--dsw-bg-secondary, #16213e)",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 12
                }
              },
              (0, import_react.createElement)(
                "span",
                { style: { color: "var(--dsw-text-secondary,#888)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                `Selected:"${selectedText.slice(0, 60)}${selectedText.length > 60 ? "..." : ""}"`
              ),
              (0, import_react.createElement)("button", {
                onClick: handleTranslateSelection,
                disabled: translating,
                style: {
                  background: translating ? "#555" : "var(--dsw-accent,#4f46e5)",
                  border: "none",
                  color: "white",
                  borderRadius: 4,
                  padding: "4px10px",
                  fontSize: 11,
                  cursor: translating ? "not-allowed" : "pointer",
                  whiteSpace: "nowrap"
                }
              }, translating ? "Translating..." : "\u{1F310}Translate Selection")
            )
          ),
          // Right: Translation+ QA
          (0, import_react.createElement)(
            "div",
            {
              style: {
                flex: 1,
                display: "flex",
                flexDirection: "column",
                minWidth: 0
              }
            },
            // Translationarea
            (0, import_react.createElement)(
              "div",
              {
                style: {
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  minHeight: 0
                }
              },
              (0, import_react.createElement)("div", {
                style: {
                  padding: "10px16px",
                  fontWeight: 600,
                  borderBottom: "1pxsolid var(--dsw-border,#333)",
                  color: "var(--dsw-text, #e0e0e0)",
                  fontSize: 13,
                  background: "var(--dsw-bg-secondary,#16213e)"
                }
              }, "\u{1F310} Translation"),
              translationError && (0, import_react.createElement)("div", {
                style: { padding: "6px12px", color: "#fca5a5", fontSize: 12, background: "rgba(127,29,29,0.25)" }
              }, translationError),
              (0, import_react.createElement)(
                "div",
                {
                  style: {
                    flex: 1,
                    padding: 16,
                    overflow: "auto",
                    color: "var(--dsw-text, #e0e0e0)",
                    fontSize: 14,
                    lineHeight: 1.7,
                    whiteSpace: "pre-wrap",
                    fontFamily: "Georgia,serif"
                  }
                },
                translation ? translation : (0, import_react.createElement)(
                  "span",
                  { style: { color: "var(--dsw-text-secondary,#666)" } },
                  selectedText ? 'Click"Translate Selection"to translate the selectedtext.' : 'Click"Translate All"to translate the entire paper,or select text totranslatea specific passage.'
                )
              )
            ),
            // Divider
            (0, import_react.createElement)("div", {
              style: { height: 1, background: "var(--dsw-border, #333)" }
            }),
            // QA Chatarea
            (0, import_react.createElement)(
              "div",
              {
                style: {
                  height: 220,
                  display: "flex",
                  flexDirection: "column",
                  borderTop: "1pxsolid var(--dsw-border, #333)"
                }
              },
              (0, import_react.createElement)(
                "div",
                {
                  style: {
                    padding: "8px12px",
                    fontWeight: 600,
                    borderBottom: "1pxsolid var(--dsw-border, #333)",
                    color: "var(--dsw-text, #e0e0e0)",
                    fontSize: 12,
                    background: "var(--dsw-bg-secondary, #16213e)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between"
                  }
                },
                (0, import_react.createElement)("span", null, "\u{1F4AC} Q&A"),
                (0, import_react.createElement)("span", { style: { fontSize: 11, color: "var(--dsw-text-secondary, #666)" } }, "Askquestions about thepaper")
              ),
              status && (0, import_react.createElement)("div", {
                style: { padding: "5px12px", color: "var(--dsw-text, #e0e0e0)", fontSize: 11, background: "var(--dsw-input, #2a2a2a)" }
              }, status),
              error && (0, import_react.createElement)("div", {
                style: { padding: "5px12px", color: "#fca5a5", fontSize: 11, background: "rgba(127,29,29,0.25)" }
              }, error),
              (0, import_react.createElement)(
                "div",
                {
                  style: { flex: 1, overflow: "auto", padding: 8, display: "flex", flexDirection: "column", gap: 6 }
                },
                ...qaMessages.map(
                  (msg, i) => (0, import_react.createElement)("div", {
                    key: i,
                    style: {
                      padding: "6px10px",
                      borderRadius: 8,
                      maxWidth: "85%",
                      alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                      background: msg.role === "user" ? "var(--dsw-accent,#4f46e5)" : "var(--dsw-input, #2a2a2a)",
                      color: "var(--dsw-text, #e0e0e0)",
                      fontSize: 13,
                      lineHeight: 1.4,
                      wordBreak: "break-word"
                    }
                  }, msg.text)
                ),
                qaLoading && (0, import_react.createElement)("div", {
                  style: {
                    padding: "6px10px",
                    borderRadius: 8,
                    maxWidth: "60%",
                    alignSelf: "flex-start",
                    background: "var(--dsw-input,#2a2a2a)",
                    color: "var(--dsw-text-secondary,#888)",
                    fontSize: 13,
                    fontStyle: "italic"
                  }
                }, "Thinking..."),
                (0, import_react.createElement)("div", { ref: chatEndRef })
              ),
              (0, import_react.createElement)(
                "div",
                {
                  style: { display: "flex", gap: 6, padding: "6px10px", borderTop: "1px solidvar(--dsw-border, #444)" }
                },
                (0, import_react.createElement)("input", {
                  value: qaInput,
                  onChange: (e) => setQaInput(e.target.value),
                  onKeyDown: (e) => {
                    if (e.key === "Enter") handleAsk();
                  },
                  placeholder: "Aska question about the paper...",
                  disabled: qaLoading,
                  style: {
                    flex: 1,
                    padding: "6px10px",
                    borderRadius: 6,
                    border: "1pxsolid var(--dsw-border, #444)",
                    background: "var(--dsw-input, #2a2a2a)",
                    color: "var(--dsw-text,#fff)",
                    fontSize: 13,
                    outline: "none"
                  }
                }),
                (0, import_react.createElement)("button", {
                  onClick: handleAsk,
                  disabled: qaLoading || !qaInput.trim(),
                  style: {
                    padding: "6px14px",
                    borderRadius: 6,
                    border: "none",
                    background: qaLoading ? "#555" : "var(--dsw-accent, #4f46e5)",
                    color: "white",
                    cursor: qaLoading ? "not-allowed" : "pointer",
                    fontSize: 13,
                    fontWeight: 500
                  }
                }, "Ask")
              )
            )
          )
        );
      }
      return (0, import_react.createElement)(
        "div",
        { style: { position: "fixed", bottom: 20, right: 20, zIndex: 9999 } },
        open ? (0, import_react.createElement)(
          "div",
          {
            style: {
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.7)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 1e4
            },
            onClick: () => setOpen(false)
          },
          (0, import_react.createElement)(
            "div",
            {
              style: {
                width: "95vw",
                height: "92vh",
                background: "var(--dsw-bg,#1a1a2e)",
                borderRadius: 12,
                display: "flex",
                flexDirection: "row",
                overflow: "hidden",
                border: "1pxsolid var(--dsw-border, #333)",
                boxShadow: "08px32px rgba(0,0,0,0.4)"
              },
              onClick: (e) => e.stopPropagation()
            },
            // Left sidebar:File browser (260px)
            activeView === "browser" || activeView === "reader" ? (0, import_react.createElement)("div", {
              style: {
                width: 260,
                minWidth: 260,
                borderRight: "1pxsolid var(--dsw-border, #333)",
                display: "flex",
                flexDirection: "column"
              }
            }, renderFileBrowser()) : null,
            // Maincontentarea
            (0, import_react.createElement)(
              "div",
              {
                style: {
                  flex: 1,
                  display: "flex",
                  flexDirection: "column",
                  minWidth: 0
                }
              },
              activeView === "browser" ? (0, import_react.createElement)(
                "div",
                {
                  style: {
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--dsw-text-secondary,#666)",
                    fontSize: 15
                  }
                },
                (0, import_react.createElement)(
                  "div",
                  { style: { textAlign: "center" } },
                  (0, import_react.createElement)("div", { style: { fontSize: 48, marginBottom: 16 } }, "\u{1F4C4}"),
                  (0, import_react.createElement)("div", null, "Select a file from the sidebar tostart reading"),
                  (0, import_react.createElement)(
                    "div",
                    { style: { fontSize: 13, marginTop: 8, color: "var(--dsw-text-secondary,#888)" } },
                    "Supported:.txt, .md,.py, .js,.ts,.html, .css,.json, .yaml, .xml, .csv"
                  )
                )
              ) : renderReader()
            )
          )
        ) : (0, import_react.createElement)("button", {
          onClick: () => {
            setActiveView("browser");
            setOpen(true);
          },
          style: {
            width: 52,
            height: 52,
            borderRadius: "50%",
            border: "none",
            background: "var(--dsw-accent,#4f46e5)",
            color: "white",
            fontSize: 22,
            cursor: "pointer",
            boxShadow: "04px12pxrgba(0,0,0,0.3)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transition: "transform 0.2s"
          },
          onMouseEnter: (e) => {
            e.currentTarget.style.transform = "scale(1.1)";
          },
          onMouseLeave: (e) => {
            e.currentTarget.style.transform = "scale(1)";
          }
        }, "\u{1F4C4}")
      );
    }
  ));
}
function formatSize(bytes) {
  if (bytes === 0) return "0B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + "" + sizes[i];
}
