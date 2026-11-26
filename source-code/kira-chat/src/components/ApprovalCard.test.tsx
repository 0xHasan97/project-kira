import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ApprovalCard } from "./ApprovalCard.tsx";

const approval = { id: "a1", tool: "write_file", risk: "write", arguments: { path: "a.txt" } };

it("calls allow with the typed secret", async () => {
  const decide = vi.fn().mockResolvedValue(undefined);
  render(<ApprovalCard approval={approval} onDecide={decide} />);
  expect(screen.getByText(/write_file/)).toBeTruthy();
  expect(screen.getByText(/a\.txt/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("approval secret"), { target: { value: "s3cret" } });
  fireEvent.click(screen.getByRole("button", { name: "allow" }));
  await waitFor(() => expect(decide).toHaveBeenCalledWith("a1", "allow", "s3cret"));
});

it("denies with the typed secret, and keeps deny dead until one is typed", async () => {
  const decide = vi.fn().mockResolvedValue(undefined);
  render(<ApprovalCard approval={approval} onDecide={decide} />);
  expect((screen.getByRole("button", { name: "deny" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("approval secret"), { target: { value: "s3cret" } });
  fireEvent.click(screen.getByRole("button", { name: "deny" }));
  await waitFor(() => expect(decide).toHaveBeenCalledWith("a1", "deny", "s3cret"));
});

it("keeps allow dead until a secret is typed, and reports a refusal", async () => {
  const decide = vi.fn().mockRejectedValue(new Error("unauthorized: this write needs the confirm secret"));
  render(<ApprovalCard approval={approval} onDecide={decide} />);
  expect((screen.getByRole("button", { name: "allow" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("approval secret"), { target: { value: "wrong" } });
  expect((screen.getByRole("button", { name: "allow" }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "allow" }));
  expect((await screen.findByText(/unauthorized/)).textContent).toContain("confirm secret");
});
