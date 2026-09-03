import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Dialog } from "./dialog";

describe("Dialog", () => {
  it("renders nothing when closed", () => {
    render(
      <Dialog open={false} title="标题" onClose={() => {}}>
        <p>内容</p>
      </Dialog>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("exposes an accessible modal when open", () => {
    render(
      <Dialog open title="删除确认" onClose={() => {}}>
        <p>此操作不可撤销。</p>
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("删除确认");
    expect(screen.getByText("此操作不可撤销。")).toBeInTheDocument();
  });

  it("moves focus into the dialog on open", () => {
    render(
      <Dialog open title="标题" onClose={() => {}}>
        <button type="button">第一个按钮</button>
      </Dialog>,
    );
    // Focus moves inside the dialog; the first focusable control is the close
    // button in the header.
    expect(screen.getByRole("button", { name: "关闭对话框" })).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Dialog open title="标题" onClose={onClose}>
        <button type="button">按钮</button>
      </Dialog>,
    );
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("traps Tab focus within the dialog", async () => {
    const user = userEvent.setup();
    render(
      <Dialog open title="标题" onClose={() => {}}>
        <button type="button">第一</button>
        <button type="button">第二</button>
      </Dialog>,
    );
    const close = screen.getByRole("button", { name: "关闭对话框" });
    const first = screen.getByRole("button", { name: "第一" });
    const second = screen.getByRole("button", { name: "第二" });
    expect(close).toHaveFocus();
    await user.tab();
    expect(first).toHaveFocus();
    await user.tab();
    expect(second).toHaveFocus();
    // Tabbing past the last element wraps to the first.
    await user.tab();
    expect(close).toHaveFocus();
    // Shift+Tab from the first wraps to the last.
    await user.tab({ shift: true });
    expect(second).toHaveFocus();
  });
});
