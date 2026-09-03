import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./button";
import { TextField } from "./text-field";

describe("TextField", () => {
  it("associates the error message with the input", () => {
    render(<TextField label="用户名" defaultValue="" error="用户名不能为空。" />);
    const input = screen.getByLabelText("用户名");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const error = screen.getByRole("alert");
    expect(error).toHaveTextContent("用户名不能为空。");
    expect(input.getAttribute("aria-describedby")).toContain(error.id);
  });

  it("has no error association when valid", () => {
    render(<TextField label="邮箱" defaultValue="" />);
    const input = screen.getByLabelText("邮箱");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("toggles password visibility", async () => {
    const user = userEvent.setup();
    render(<TextField label="密码" type="password" revealable />);
    const input = screen.getByLabelText("密码");
    expect(input).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "显示密码" }));
    expect(input).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "隐藏密码" }));
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("Button", () => {
  it("disables and marks busy while loading, keeping content", () => {
    render(<Button loading>保存</Button>);
    const button = screen.getByRole("button", { name: /保存/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("fires onClick when active", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>登录</Button>);
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
