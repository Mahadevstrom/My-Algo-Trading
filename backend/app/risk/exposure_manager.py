class ExposureManager:
    def open_exposure(self, open_positions: list[dict]) -> float:
        return round(
            sum(float(item.get("entry_price") or 0) * int(item.get("quantity") or 0) for item in open_positions),
            2,
        )

    def would_exceed(self, context: dict, open_positions: list[dict], max_exposure: float) -> bool:
        current = self.open_exposure(open_positions)
        requested = float(context.get("entry_price") or 0) * int(context.get("quantity") or 0)
        return current + requested > max_exposure
