// QwenPaw browser-side injected engine. Self-contained, zero external deps.
// Injected via CDP Runtime.evaluate; idempotent.
(function () {
  if (window.__qwenpaw) return;

  const IMPLICIT_ROLES = {
    a: "link",
    article: "article",
    aside: "complementary",
    button: "button",
    footer: "contentinfo",
    form: "form",
    h1: "heading",
    h2: "heading",
    h3: "heading",
    h4: "heading",
    h5: "heading",
    h6: "heading",
    header: "banner",
    img: "img",
    main: "main",
    nav: "navigation",
    ol: "list",
    option: "option",
    select: "combobox",
    summary: "button",
    table: "table",
    textarea: "textbox",
    ul: "list",
  };

  function kwargs(step) {
    return Object.fromEntries(step.kwargs || []);
  }

  function unique(elements) {
    return Array.from(new Set(elements));
  }

  function descendants(root) {
    if (!root || !root.querySelectorAll) return [];
    return Array.from(root.querySelectorAll("*"));
  }

  function matchingDescendants(roots, predicate) {
    return unique(
      roots.flatMap(function (root) {
        return descendants(root).filter(predicate);
      }),
    );
  }

  function matchingFrames(roots, selector) {
    return unique(
      roots.flatMap(function (root) {
        return root.querySelectorAll
          ? Array.from(root.querySelectorAll(selector))
          : [];
      }),
    ).filter(function (element) {
      return element.tagName && element.tagName.toLowerCase() === "iframe";
    });
  }

  function frameMetadata(frame, selector) {
    const rect = frame.getBoundingClientRect();
    return {
      selector: selector,
      src:
        frame.src ||
        frame.getAttribute("src") ||
        (frame.hasAttribute("srcdoc") ? "about:srcdoc" : ""),
      name: frame.name || frame.getAttribute("name") || "",
      x: rect.left,
      y: rect.top,
    };
  }

  function normalizedText(element) {
    return (element.textContent || "").replace(/\s+/g, " ").trim();
  }

  function foldText(value) {
    return String(value == null ? "" : value)
      .replace(/\s+/g, " ").trim().toLowerCase();
  }

  function normalizedMatch(haystack, needle) {
    return foldText(haystack).indexOf(foldText(needle)) !== -1;
  }

  function rawWhitespaceMatch(haystack, needle) {
    return String(haystack == null ? "" : haystack)
      .toLowerCase()
      .indexOf(String(needle == null ? "" : needle).toLowerCase()) !== -1;
  }

  function matchesText(element, wanted) {
    return normalizedMatch(normalizedText(element), wanted);
  }

  function roleFor(element) {
    if (element.getAttribute("role")) {
      return element.getAttribute("role");
    }
    if (typeof element.computedRole === "string" && element.computedRole) {
      return element.computedRole;
    }
    const tag = element.tagName.toLowerCase();
    if (tag === "input") {
      const type = (element.getAttribute("type") || "text").toLowerCase();
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (["button", "submit", "reset", "image"].includes(type)) {
        return "button";
      }
      if (type === "range") return "slider";
      return "textbox";
    }
    if (tag === "a" && element.hasAttribute("href")) return "link";
    return IMPLICIT_ROLES[tag] || null;
  }

  function accessibleName(element) {
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const name = labelledBy
        .split(/\s+/)
        .map(function (id) {
          const label = document.getElementById(id);
          return label ? normalizedText(label) : "";
        })
        .join(" ")
        .trim();
      if (name) return name;
    }
    return (
      element.getAttribute("aria-label") ||
      element.getAttribute("alt") ||
      element.getAttribute("title") ||
      normalizedText(element)
    );
  }

  function labelsFor(root, text) {
    const labels = descendants(root).filter(function (element) {
      return element.tagName.toLowerCase() === "label" && matchesText(element, text);
    });
    return unique(
      labels.flatMap(function (label) {
        if (label.control) return [label.control];
        const forId = label.getAttribute("for");
        if (forId) {
          const control = document.getElementById(forId);
          return control ? [control] : [];
        }
        return descendants(label).filter(function (element) {
          return /^(input|textarea|select)$/i.test(element.tagName);
        });
      }),
    );
  }

  function applyStep(candidates, step) {
    const method = step.method;
    const args = step.args || [];
    const options = kwargs(step);
    if (method === "frame_locator") {
      const selector = String(args[0] || "");
      const frames = matchingFrames(candidates, selector);
      const frameDocuments = frames
        .filter(function (frame) {
          return Boolean(frame.contentDocument);
        })
        .map(function (frame) {
          return frame.contentDocument;
        });
      if (frameDocuments.length) return frameDocuments;
      const frame = frames[0];
      if (frame) {
        const metadata = frameMetadata(frame, selector);
        throw new Error(
          "QWENPAW_CROSS_ORIGIN_FRAME:" +
            JSON.stringify({
              selector: selector,
              src: metadata.src,
              name: metadata.name,
            }),
        );
      }
      return [];
    }
    if (method === "locator") {
      const selector = String(args[0] || "");
      return unique(
        candidates.flatMap(function (root) {
          return root.querySelectorAll
            ? Array.from(root.querySelectorAll(selector))
            : [];
        }),
      );
    }
    if (method === "get_by_role") {
      const role = String(args[0] || "");
      return matchingDescendants(candidates, function (element) {
        return (
          roleFor(element) === role &&
          (!options.name || normalizedMatch(accessibleName(element), options.name))
        );
      });
    }
    if (method === "get_by_text") {
      const matches = matchingDescendants(candidates, function (element) {
        return matchesText(element, args[0]);
      });
      // A text query should select the smallest matching element. Without
      // this, document-level queries also return every matching ancestor.
      return matches.filter(function (element) {
        return !matches.some(function (other) {
          return other !== element && element.contains(other);
        });
      });
    }
    if (method === "get_by_label") {
      return unique(
        candidates.flatMap(function (root) {
          return labelsFor(root, args[0]);
        }),
      );
    }
    if (method === "get_by_placeholder") {
      return matchingDescendants(candidates, function (element) {
        return rawWhitespaceMatch(
          element.getAttribute("placeholder") || "",
          args[0],
        );
      });
    }
    if (method === "filter") {
      const wanted = options.has_text;
      return candidates.filter(function (element) {
        return wanted === undefined || matchesText(element, wanted);
      });
    }
    if (method === "first") return candidates.slice(0, 1);
    if (method === "last") return candidates.slice(-1);
    if (method === "nth") {
      const index = Number(args[0]);
      return Number.isInteger(index) && index >= 0
        ? candidates.slice(index, index + 1)
        : [];
    }
    throw new Error("unsupported locator step: " + method);
  }

  function resolve(spec) {
    return (spec || []).reduce(applyStep, [document]);
  }

  function resolveOne(spec) {
    const elements = resolve(spec);
    if (elements.length !== 1) {
      throw new Error(
        "strict locator expected one match, got " + elements.length,
      );
    }
    return elements[0];
  }

  function isVisible(element) {
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function frameViewportOffset(element) {
    let x = 0;
    let y = 0;
    let view = element.ownerDocument && element.ownerDocument.defaultView;
    while (view && view !== window) {
      const frame = view.frameElement;
      if (!frame) break;
      const rect = frame.getBoundingClientRect();
      x += rect.left;
      y += rect.top;
      view = frame.ownerDocument && frame.ownerDocument.defaultView;
    }
    return { x: x, y: y };
  }

  function stateMatches(elements, state) {
    if (state === "attached") return elements.length > 0;
    if (state === "visible") return elements.some(isVisible);
    if (state === "hidden") {
      return elements.length === 0 || elements.every(function (element) {
        return !isVisible(element);
      });
    }
    if (state === "detached") return elements.length === 0;
    throw new Error("unsupported locator wait state: " + state);
  }

  function read(element, property, args) {
    switch (property) {
      case "text_content":
        return element.textContent;
      case "inner_text":
        return element.innerText;
      case "is_visible":
        return isVisible(element);
      case "is_enabled":
        return !element.disabled;
      case "get_attribute":
        return element.getAttribute(args[0]);
      case "input_value":
        return element.value;
      case "inner_html":
        return element.innerHTML;
      default:
        throw new Error("unsupported locator property: " + property);
    }
  }

  function dispatchInputAndChange(element) {
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setValue(element, value) {
    const prototype = Object.getPrototypeOf(element);
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor && descriptor.set) {
      descriptor.set.call(element, value);
    } else {
      element.value = value;
    }
  }

  function action(element, name, params) {
    const options = params || {};
    switch (name) {
      case "scroll":
      case "scroll_into_view":
        element.scrollIntoView({ block: "center", inline: "center" });
        return null;
      case "focus":
        element.focus();
        return null;
      case "blur":
        element.blur();
        return null;
      case "clear":
        setValue(element, "");
        dispatchInputAndChange(element);
        return null;
      case "fill":
        setValue(element, String(options.value || ""));
        dispatchInputAndChange(element);
        return null;
      case "type_text": {
        const text = String(options.text || "");
        for (const character of text) {
          setValue(element, String(element.value || "") + character);
          element.dispatchEvent(new Event("input", { bubbles: true }));
        }
        element.dispatchEvent(new Event("change", { bubbles: true }));
        return null;
      }
      case "set_checked":
        element.checked = Boolean(options.checked);
        dispatchInputAndChange(element);
        return element.checked;
      case "select_option": {
        const values = options.values || [options.value || options.option];
        const selected = new Set(values.map(String));
        Array.from(element.options || []).forEach(function (option) {
          option.selected = selected.has(option.value);
        });
        dispatchInputAndChange(element);
        return Array.from(element.selectedOptions || []).map(function (option) {
          return option.value;
        });
      }
      default:
        throw new Error("unsupported DOM locator action: " + name);
    }
  }

  window.__qwenpaw = {
    resolve: resolve,
    resolveOne: resolveOne,
    resolveAndRead: function (spec, property, args) {
      return read(resolveOne(spec), property, args || []);
    },
    resolveAndReadAll: function (spec, property, args) {
      return resolve(spec).map(function (element) {
        return read(element, property, args || []);
      });
    },
    resolveAndAction: function (spec, name, params) {
      return action(resolveOne(spec), name, params);
    },
    resolveAndGetClickTarget: function (spec) {
      const element = resolveOne(spec);
      element.scrollIntoView({ block: "center", inline: "center" });
      const rect = element.getBoundingClientRect();
      const offset = frameViewportOffset(element);
      return {
        x: offset.x + rect.left + rect.width / 2,
        y: offset.y + rect.top + rect.height / 2,
        width: rect.width,
        height: rect.height,
      };
    },
    resolveAndBoundingBox: function (spec) {
      const element = resolveOne(spec);
      if (!isVisible(element)) return null;
      const rect = element.getBoundingClientRect();
      const offset = frameViewportOffset(element);
      return {
        x: offset.x + rect.left,
        y: offset.y + rect.top,
        width: rect.width,
        height: rect.height,
      };
    },
    resolveAndClipRect: function (spec) {
      const element = resolveOne(spec);
      if (!isVisible(element)) return null;
      const rect = element.getBoundingClientRect();
      const offset = frameViewportOffset(element);
      return {
        x: offset.x + rect.left + window.scrollX,
        y: offset.y + rect.top + window.scrollY,
        width: rect.width,
        height: rect.height,
      };
    },
    resolveAndCount: function (spec) {
      return resolve(spec).length;
    },
    frameInfo: function (selector) {
      const frames = matchingFrames([document], String(selector || ""));
      if (frames.length !== 1) {
        throw new Error(
          "strict frame locator expected one match, got " + frames.length,
        );
      }
      return frameMetadata(frames[0], String(selector || ""));
    },
    waitFor: async function (spec, state, timeoutMs) {
      const deadline = Date.now() + Number(timeoutMs);
      while (true) {
        if (stateMatches(resolve(spec), state)) return true;
        if (Date.now() >= deadline) {
          throw new Error(
            "wait_for timed out: " + state + " not reached in " + timeoutMs + "ms",
          );
        }
        await new Promise(function (done) {
          window.setTimeout(done, 50);
        });
      }
    },
  };
})();
