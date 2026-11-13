import { expect, it } from "vitest";
import { directoryBreadcrumbs } from "./directoryBreadcrumbs";

it.each([
  ["/Users/ray/Desktop", ["/", "/Users", "/Users/ray", "/Users/ray/Desktop"]],
  ["/", ["/"]],
  ["C:\\Users\\ray", ["C:\\", "C:\\Users", "C:\\Users\\ray"]],
  ["C:/Users/ray/", ["C:/", "C:/Users", "C:/Users/ray"]],
  [
    "\\\\server\\share\\work",
    ["\\\\server\\share\\", "\\\\server\\share\\work"],
  ],
])("keeps valid ancestor targets for %s", (path, expected) => {
  expect(directoryBreadcrumbs(path).map((item) => item.path)).toEqual(expected);
});
