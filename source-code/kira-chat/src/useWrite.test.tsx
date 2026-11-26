import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KiraApiError } from "./contracts.ts";
import { ConfirmProvider } from "./confirm.tsx";
import { useWrite } from "./useWrite.ts";

const refresh = vi.fn();
const unauthorized = new KiraApiError(
  { code: "unauthorized", message: "this write needs the confirm secret", status: 401, retryable: false },
  401,
);
const badBody = new KiraApiError(
  { code: "config_error", message: "monthly_cap must be >= 0", status: 400, retryable: false },
  400,
);

function Hook({ act, plain }: { act: (secret: string) => Promise<unknown>; plain?: () => Promise<unknown> }) {
  const write = useWrite(refresh);
  return (
    <>
      <button
        type="button"
        disabled={write.busy}
        onClick={() => void write.run("turn groq off", "PUT /v1/kira/providers/groq/settings", false, act)}
      >
        {`write ${write.note ?? "clean"}`}
      </button>
      {plain && (
        <button type="button" disabled={write.busy} onClick={() => void write.quick(plain)}>
          {`quick ${write.note ?? "clean"}`}
        </button>
      )}
    </>
  );
}

async function open(summary = "turn groq off") {
  fireEvent.click(screen.getByRole("button", { name: /^write / }));
  expect(await screen.findByText(summary)).toBeTruthy();
}

describe("useWrite", () => {
  it("does not act at all when the human cancels", async () => {
    const act = vi.fn(async () => undefined);
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(act).not.toHaveBeenCalled());
    expect(refresh).not.toHaveBeenCalled();
  });

  it("acts with the secret, then re-reads", async () => {
    const act = vi.fn(async (_secret: string) => undefined);
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith("s3cret"));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "write clean" })).toBeTruthy();
  });

  it("keeps a real failure as the engine's own words and does not re-ask", async () => {
    const act = vi.fn(async () => {
      throw badBody;
    });
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /config_error/ })).toBeTruthy());
    expect(act).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("turn groq off")).toBeNull();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("asks again on a refused secret and takes the second one", async () => {
    let calls = 0;
    const act = vi.fn(async () => {
      calls += 1;
      if (calls === 1) throw unauthorized;
      return undefined;
    });
    render(
      <ConfirmProvider>
        <Hook act={act} />
      </ConfirmProvider>,
    );
    await open();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    expect(await screen.findByText(/refused that secret; type it again/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(act).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("runs a secret-free write with no dialog and re-reads", async () => {
    const plain = vi.fn(async () => undefined);
    render(
      <ConfirmProvider>
        <Hook act={vi.fn()} plain={plain} />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^quick / }));
    await waitFor(() => expect(plain).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
  });

  it("shows a secret-free write's refusal on the screen instead of a dialog loop", async () => {
    const plain = vi.fn(async () => {
      throw badBody;
    });
    render(
      <ConfirmProvider>
        <Hook act={vi.fn()} plain={plain} />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^quick / }));
    expect(await screen.findByText(/^quick config_error: monthly_cap must be >= 0$/)).toBeTruthy();
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
  });
});
