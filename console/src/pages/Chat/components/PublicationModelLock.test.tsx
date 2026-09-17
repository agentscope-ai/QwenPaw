// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PublicationModelLock from "./PublicationModelLock";

describe("PublicationModelLock", () => {
  it("shows the immutable version and model without an editor", () => {
    render(<PublicationModelLock version="r2" providerId="provider" model="model" />);
    expect(screen.getByText("r2 · provider/model")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
