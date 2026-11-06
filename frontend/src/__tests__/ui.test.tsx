import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Amount, Badge, Button, Empty, Modal, Pagination } from "@/components/ui";

describe("ui components", () => {
  it("renders amounts with direction", () => {
    render(<Amount value="25.5" direction="in" />);
    expect(screen.getByText("+GH₵25.50")).toBeInTheDocument();
  });
  it("title-cases status badges", () => {
    render(<Badge>partially_refunded</Badge>);
    expect(screen.getByText("Partially Refunded")).toBeInTheDocument();
  });
  it("disables a loading button", () => {
    render(<Button loading>Pay</Button>);
    expect(screen.getByRole("button", { name: "Pay" })).toBeDisabled();
  });
  it("shows empty states", () => {
    render(<Empty title="Nothing here" body="Add something" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
  it("closes modal on escape", async () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="Confirm">body</Modal>);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
  it("paginates", async () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={20} total={45} onPage={onPage} />);
    expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
});
