import { render, screen } from "@testing-library/react";
import SystemStatus from "@/components/SystemStatus";

describe("SystemStatus", () => {
  it("renders nothing when heartbeat is null", () => {
    const { container } = render(<SystemStatus heartbeat={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a live indicator for a recent heartbeat", () => {
    render(
      <SystemStatus
        heartbeat={{
          last_successful_run: new Date(Date.now() - 5 * 60_000).toISOString(),
          run_count_24h: 48,
        }}
      />
    );
    const status = screen.getByTestId("system-status");
    expect(status).toHaveAttribute("data-level", "live");
    expect(status).toHaveTextContent("system status: live");
  });

  it("shows a down indicator for a very stale heartbeat", () => {
    render(
      <SystemStatus
        heartbeat={{
          last_successful_run: new Date(Date.now() - 6 * 60 * 60_000).toISOString(),
          run_count_24h: 0,
        }}
      />
    );
    const status = screen.getByTestId("system-status");
    expect(status).toHaveAttribute("data-level", "down");
    expect(status).toHaveTextContent("system status: stale");
  });
});
