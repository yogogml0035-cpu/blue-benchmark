import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ParticleField } from "./particle-field";

describe("ParticleField", () => {
  it("renders a decorative canvas", () => {
    const { container } = render(<ParticleField />);
    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    expect(canvas).toHaveAttribute("aria-hidden", "true");
  });

  it("does not expose the canvas to the accessibility tree", () => {
    render(<ParticleField />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
