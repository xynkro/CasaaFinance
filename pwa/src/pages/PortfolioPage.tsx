import type { SnapshotRow, PositionRow } from "../data";
import { PnlCard } from "../cards/PnlCard";
import { PositionsTable } from "../components/PositionsTable";

export function PortfolioPage({
  label,
  currency,
  snapshot,
  positions,
  loading,
}: {
  label: string;
  currency: "USD" | "SGD";
  snapshot: SnapshotRow | null;
  positions: PositionRow[];
  loading: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <PnlCard label={label} currency={currency} snapshot={snapshot} positions={positions} loading={loading} />
      </div>
      <div className="fade-up fade-up-2">
        <PositionsTable positions={positions} currency={currency} />
      </div>
    </div>
  );
}
