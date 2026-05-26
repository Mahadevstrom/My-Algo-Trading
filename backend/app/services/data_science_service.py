import logging
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from datetime import datetime

logger = logging.getLogger(__name__)

class DataScienceService:
    """
    Core service for advanced quantitative analytics, predictive modeling,
    and performance calculations.
    """
    def __init__(self):
        pass

    def calculate_trade_distribution(self, trades: list[dict]) -> dict:
        """
        Calculates the probability distribution of trade PnL.
        Useful for building bell curves in the frontend.
        """
        if not trades:
            return {"status": "NO_DATA"}
            
        df = pd.DataFrame(trades)
        if 'pnl' not in df.columns:
            return {"status": "NO_PNL_COLUMN"}
            
        pnl_array = df['pnl'].dropna().values
        if len(pnl_array) < 5:
            return {"status": "INSUFFICIENT_DATA", "count": len(pnl_array)}
            
        mean = np.mean(pnl_array)
        std_dev = np.std(pnl_array)
        
        # Calculate a simple histogram for the UI (10 bins)
        hist, bin_edges = np.histogram(pnl_array, bins=10)
        
        return {
            "status": "OK",
            "mean": float(mean),
            "std_dev": float(std_dev),
            "histogram": {
                "counts": hist.tolist(),
                "bin_edges": bin_edges.tolist()
            },
            "win_rate": float(np.mean(pnl_array > 0)),
            "total_trades": len(pnl_array)
        }

    def compute_advanced_metrics(self, trades: list[dict]) -> dict:
        """
        Computes Sharpe, Sortino, Max Drawdown, etc.
        """
        if not trades:
            return {"status": "NO_DATA"}
            
        df = pd.DataFrame(trades)
        if 'pnl' not in df.columns:
            return {"status": "NO_PNL_COLUMN"}
            
        pnl = df['pnl'].dropna().values
        if len(pnl) == 0:
            return {"status": "NO_DATA"}
            
        cumulative_pnl = np.cumsum(pnl)
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = running_max - cumulative_pnl
        max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0
        
        # Simplified Sharpe (Assuming risk-free rate = 0)
        mean_pnl = np.mean(pnl)
        std_pnl = np.std(pnl)
        sharpe = float(mean_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0
        
        return {
            "status": "OK",
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "profit_factor": float(np.sum(pnl[pnl > 0]) / abs(np.sum(pnl[pnl < 0]))) if np.sum(pnl[pnl < 0]) != 0 else float('inf')
        }

    def classify_market_regime(self, db: Session, symbol: str, interval: str, lookback_bars: int = 2000) -> dict:
        """
        Runs unsupervised K-Means clustering on historical candles to identify the current market regime.
        """
        from app.models.candle import Candle
        from sqlalchemy import select
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        import pandas as pd
        import numpy as np

        # Fetch candles
        candles = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == symbol, Candle.interval == interval)
                .order_by(Candle.timestamp.desc())
                .limit(lookback_bars)
            )
        )
        # Reverse to chronological order
        candles.reverse()

        if len(candles) < 100:
            return {
                "status": "INSUFFICIENT_DATA",
                "message": f"Found only {len(candles)} candles. Ingest at least 100 candles via Historical Downloader to train the regime model.",
                "total_candles": len(candles)
            }

        # Convert to DataFrame
        data = []
        for c in candles:
            data.append({
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume or 0.0
            })
        df = pd.DataFrame(data)

        # Feature Engineering
        df["returns"] = df["close"].pct_change()
        df["range"] = (df["high"] - df["low"]) / df["close"]
        df["volatility"] = df["returns"].rolling(window=10).std()
        df.dropna(inplace=True)

        if len(df) < 50:
            return {
                "status": "INSUFFICIENT_DATA",
                "message": "Insufficient data after rolling features calculation.",
                "total_candles": len(candles)
            }

        # Prepare Features
        features = df[["returns", "range", "volatility"]].values
        scaler = StandardScaler()
        scaled_features = scaler.fit_transform(features)

        # Fit KMeans
        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(scaled_features)
        df["cluster"] = clusters

        # Classify and map cluster names
        # Calculate cluster means
        cluster_means = df.groupby("cluster")[["returns", "volatility"]].mean()
        
        # Determine labels:
        # Volatile / Bearish = High Volatility, Negative/Low Returns
        # Chop = Low Volatility
        # Bullish Trend = Medium/High Volatility, Positive Returns
        vol_sorted = cluster_means.sort_values(by="volatility")
        
        # Low volatility is always CHOP
        chop_cluster = vol_sorted.index[0]
        
        remaining = vol_sorted.index[1:]
        if cluster_means.loc[remaining[0], "returns"] > cluster_means.loc[remaining[1], "returns"]:
            bullish_cluster = remaining[0]
            bearish_cluster = remaining[1]
        else:
            bullish_cluster = remaining[1]
            bearish_cluster = remaining[0]

        regime_labels = {
            chop_cluster: "CHOP / RANGE-BOUND",
            bearish_cluster: "BEARISH / VOLATILE",
            bullish_cluster: "BULLISH TREND"
        }
        df["regime"] = df["cluster"].map(regime_labels)

        # Current State
        current_row = df.iloc[-1]
        current_regime = current_row["regime"]
        
        # Calculate Confidence Score based on proximity to cluster center
        current_scaled = scaled_features[-1].reshape(1, -1)
        distances = kmeans.transform(current_scaled)[0]
        confidence = float(np.round(100 * (1.0 - (distances[current_row["cluster"]] / np.sum(distances))), 1))

        # Prep Scatter Plot Data (limit to 1000 points to avoid overloading browser)
        scatter_points = []
        plot_df = df.tail(1000)
        for _, r in plot_df.iterrows():
            scatter_points.append([
                float(r["returns"] * 100), # % Returns on X
                float(r["volatility"] * 100), # Volatility on Y
                r["regime"]
            ])

        # Cluster Distribution Counts
        counts = df["regime"].value_counts().to_dict()

        return {
            "status": "OK",
            "symbol": symbol,
            "interval": interval,
            "current_regime": current_regime,
            "confidence_score": confidence,
            "total_bars_analyzed": len(df),
            "distribution": {k: int(v) for k, v in counts.items()},
            "scatter_data": scatter_points,
            "features_mean": {
                "returns": float(df["returns"].mean() * 100),
                "volatility": float(df["volatility"].mean() * 100)
            }
        }

    def run_monte_carlo(
        self,
        trades_pnl: list[float],
        initial_capital: float = 100000.0,
        risk_per_trade_pct: float = 5.0,
        num_simulations: int = 2000,
        num_trades_per_run: int = 100,
        ruin_threshold_pct: float = 50.0,
        win_rate: float = 55.0,
        avg_win: float = 5000.0,
        avg_loss: float = 3000.0,
        source: str = "custom"
    ) -> dict:
        """
        Runs Monte Carlo stress-testing on a sequence of trades using NumPy.
        Supports:
          - 'historical': Bootstraps (resamples with replacement) from actual PnLs in trades_pnl
          - 'custom': Generates Gaussian simulated returns based on custom Win/Loss expectations
        """
        import numpy as np

        num_simulations = max(10, min(num_simulations, 10000))
        num_trades_per_run = max(5, min(num_trades_per_run, 500))

        # Check source and prepare PnL generation
        if source == "historical" and len(trades_pnl) >= 5:
            # Historical Bootstrapping
            actual_pnls = np.array(trades_pnl, dtype=float)
            # Sample indices with replacement
            indices = np.random.choice(len(actual_pnls), size=(num_simulations, num_trades_per_run))
            pnls = actual_pnls[indices]
            
            # Extract actual parameters for stats display
            hist_wins = actual_pnls[actual_pnls > 0]
            hist_losses = actual_pnls[actual_pnls < 0]
            win_rate = float(np.mean(actual_pnls > 0) * 100.0) if len(actual_pnls) > 0 else win_rate
            avg_win = float(np.mean(hist_wins)) if len(hist_wins) > 0 else avg_win
            avg_loss = float(abs(np.mean(hist_losses))) if len(hist_losses) > 0 else avg_loss
        else:
            # Custom / Parametric Simulation with slight Gaussian variance
            # Probabilities
            p_win = win_rate / 100.0
            
            # Generate win/loss decisions
            rand = np.random.rand(num_simulations, num_trades_per_run)
            wins = rand < p_win
            
            # Win PnL has some random variation (std dev = 20% of avg_win)
            win_pnls = np.random.normal(avg_win, max(1.0, avg_win * 0.2), size=(num_simulations, num_trades_per_run))
            # Loss PnL (std dev = 20% of avg_loss)
            loss_pnls = np.random.normal(-avg_loss, max(1.0, avg_loss * 0.2), size=(num_simulations, num_trades_per_run))
            
            pnls = np.where(wins, win_pnls, loss_pnls)

        # Run simulations
        # Accumulate returns
        cumulative_pnls = np.cumsum(pnls, axis=1)
        balance_paths = initial_capital + cumulative_pnls
        
        # Prepend initial capital to each path (dimension becomes num_simulations x (num_trades_per_run + 1))
        initial_caps = np.full((num_simulations, 1), initial_capital)
        equity_curves = np.hstack([initial_caps, balance_paths])
        
        # Drawdown calculation at each step
        # running_max: shape (num_simulations, num_trades_per_run + 1)
        running_max = np.maximum.accumulate(equity_curves, axis=1)
        drawdowns = running_max - equity_curves
        
        # Max drawdown percentage on running max
        # To avoid division by zero:
        safe_running_max = np.where(running_max <= 0, 1.0, running_max)
        max_drawdowns_pct = (drawdowns / safe_running_max) * 100.0
        
        # Peak drawdown per simulation path
        peak_drawdowns = np.max(max_drawdowns_pct, axis=1)
        
        # Ruin analysis: did the capital drop below the ruin threshold percent at any point?
        ruined = peak_drawdowns >= ruin_threshold_pct
        ruin_probability = float(np.mean(ruined) * 100.0)
        
        # Terminal Capital Stats
        terminal_capital = equity_curves[:, -1]
        
        # Percentiles
        terminal_stats = {
            "p5": float(np.percentile(terminal_capital, 5)),
            "p25": float(np.percentile(terminal_capital, 25)),
            "p50": float(np.percentile(terminal_capital, 50)), # Median
            "p75": float(np.percentile(terminal_capital, 75)),
            "p95": float(np.percentile(terminal_capital, 95))
        }
        
        drawdown_stats = {
            "p50": float(np.percentile(peak_drawdowns, 50)), # Median Max DD
            "p90": float(np.percentile(peak_drawdowns, 90)),
            "p95": float(np.percentile(peak_drawdowns, 95)),
            "p99": float(np.percentile(peak_drawdowns, 99))
        }

        # Keep 50 sample paths for UI plotting
        sample_curves = equity_curves[:50].tolist()
        
        # Compute summary metrics
        total_pnl = float(np.mean(terminal_capital - initial_capital))
        win_simulations_count = int(np.sum(terminal_capital > initial_capital))
        simulation_win_rate = float((win_simulations_count / num_simulations) * 100.0)

        return {
            "status": "OK",
            "source": source,
            "simulations_run": num_simulations,
            "trades_per_run": num_trades_per_run,
            "initial_capital": initial_capital,
            "ruin_threshold_pct": ruin_threshold_pct,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "ruin_probability": round(ruin_probability, 2),
            "terminal_stats": terminal_stats,
            "drawdown_stats": drawdown_stats,
            "sample_curves": sample_curves,
            "expected_pnl": round(total_pnl, 2),
            "simulation_win_rate": round(simulation_win_rate, 2)
        }

data_science_service = DataScienceService()

