"""Latency Stopwatch Benchmark Tool.

High-precision millisecond stopwatch utility with Tkinter GUI window
(and headless console mode for non-GUI / automated environments)
for visual glass-to-glass latency testing across primary and secondary displays.
"""

import argparse
import logging
import sys
import time

logger = logging.getLogger(__name__)


def measure_system_timer_resolution(samples: int = 1000) -> dict[str, float]:
    """Measure the resolution and jitter of the system's high-precision timer."""
    deltas: list[float] = []
    prev = time.perf_counter()
    for _ in range(samples):
        curr = time.perf_counter()
        d = curr - prev
        if d > 0:
            deltas.append(d)
        prev = curr

    min_res = min(deltas) if deltas else 0.0
    avg_res = (sum(deltas) / len(deltas)) if deltas else 0.0
    max_res = max(deltas) if deltas else 0.0

    return {
        'min_resolution_us': min_res * 1e6,
        'avg_resolution_us': avg_res * 1e6,
        'max_resolution_us': max_res * 1e6,
        'samples': len(deltas),
    }


def run_headless_benchmark(
    duration: float = 3.0,
    interval: float = 0.016,  # ~60 Hz tick interval
    log_output: bool = True,
) -> dict[str, float | int]:
    """Run a headless precision stopwatch benchmark for automated or headless testing."""
    start_time = time.perf_counter()
    epoch_start_ms = int(time.time() * 1000)
    ticks = 0
    intervals: list[float] = []
    last_tick_time = start_time

    if log_output:
        print(f"[Stopwatch] Starting headless benchmark (duration: {duration:.2f}s, target interval: {interval*1000:.1f}ms)...")

    while (time.perf_counter() - start_time) < duration:
        now = time.perf_counter()
        elapsed = now - start_time
        tick_delta = now - last_tick_time
        intervals.append(tick_delta)
        last_tick_time = now
        ticks += 1

        epoch_now_ms = epoch_start_ms + int(elapsed * 1000)
        ms_mod = epoch_now_ms % 1000000

        if log_output and ticks % 30 == 0:
            print(f"  Tick #{ticks:04d} | Elapsed: {elapsed:06.3f}s | Timestamp: {ms_mod:06d}ms | Delta: {tick_delta*1000:.2f}ms")

        # Sleep remaining time until next tick
        target_next = start_time + (ticks * interval)
        sleep_dur = target_next - time.perf_counter()
        if sleep_dur > 0:
            time.sleep(sleep_dur)

    total_elapsed = time.perf_counter() - start_time
    avg_fps = ticks / total_elapsed if total_elapsed > 0 else 0
    avg_interval_ms = (sum(intervals) / len(intervals) * 1000) if intervals else 0.0

    stats = {
        'duration_s': total_elapsed,
        'ticks': ticks,
        'avg_fps': avg_fps,
        'avg_interval_ms': avg_interval_ms,
    }

    if log_output:
        print(f"[Stopwatch] Completed: {ticks} ticks in {total_elapsed:.3f}s ({avg_fps:.1f} ticks/sec, avg interval: {avg_interval_ms:.2f}ms)")

    return stats


def create_latency_stopwatch(
    title: str = "Latency Timer - Drag to Secondary Display",
    width: int = 700,
    height: int = 350,
    fullscreen: bool = False,
    test_mode_ticks: int | None = None,
):
    """Create and display high-precision Tkinter stopwatch window.

    If Tkinter or a display is not available, automatically falls back to headless mode.
    If `test_mode_ticks` is set, runs for that number of update ticks and returns without blocking.
    """
    try:
        import tkinter as tk
    except ImportError:
        logger.warning("Tkinter not available. Falling back to headless stopwatch benchmark.")
        return run_headless_benchmark(duration=2.0)

    try:
        root = tk.Tk()
    except Exception as e:
        logger.warning(f"Failed to initialize Tk GUI ({e}). Falling back to headless mode.")
        return run_headless_benchmark(duration=2.0)

    root.title(title)
    root.geometry(f"{width}x{height}")
    root.configure(bg="#0b0e14")

    # State variables
    state = {
        'start_time': time.perf_counter(),
        'paused': False,
        'paused_time': 0.0,
        'total_paused_duration': 0.0,
        'tick_count': 0,
        'is_fullscreen': fullscreen,
        'last_fps_calc_time': time.perf_counter(),
        'fps_tick_count': 0,
        'current_fps': 60.0,
    }

    if fullscreen:
        root.attributes('-fullscreen', True)

    # UI Widgets
    title_label = tk.Label(
        root,
        text="GLASS-TO-GLASS LATENCY BENCHMARK TIMER",
        font=("Consolas", 14, "bold"),
        fg="#708298",
        bg="#0b0e14",
    )
    title_label.pack(pady=(12, 0))

    ms_label = tk.Label(
        root,
        text="000000 ms",
        font=("Consolas", 52, "bold"),
        fg="#00ff66",
        bg="#0b0e14",
    )
    ms_label.pack(expand=True)

    clock_label = tk.Label(
        root,
        text="Elapsed: 00:00.000 | Epoch: 0000000000000 ms",
        font=("Consolas", 16),
        fg="#00d8ff",
        bg="#0b0e14",
    )
    clock_label.pack(pady=(0, 5))

    stats_label = tk.Label(
        root,
        text="Tick: #000000 | Rate: ~60.0 FPS | [Space]: Pause  [R]: Reset  [F11]: Fullscreen",
        font=("Consolas", 11),
        fg="#85929e",
        bg="#0b0e14",
    )
    stats_label.pack(pady=(0, 10))

    def toggle_fullscreen(event=None):
        state['is_fullscreen'] = not state['is_fullscreen']
        root.attributes('-fullscreen', state['is_fullscreen'])

    def toggle_pause(event=None):
        if not state['paused']:
            state['paused'] = True
            state['paused_time'] = time.perf_counter()
            ms_label.config(fg="#ffaa00")
        else:
            state['paused'] = False
            state['total_paused_duration'] += time.perf_counter() - state['paused_time']
            ms_label.config(fg="#00ff66")

    def reset_timer(event=None):
        state['start_time'] = time.perf_counter()
        state['paused'] = False
        state['total_paused_duration'] = 0.0
        state['tick_count'] = 0
        state['fps_tick_count'] = 0
        state['last_fps_calc_time'] = time.perf_counter()
        ms_label.config(fg="#00ff66")

    root.bind("<space>", toggle_pause)
    root.bind("<r>", reset_timer)
    root.bind("<R>", reset_timer)
    root.bind("<F11>", toggle_fullscreen)
    root.bind("<Escape>", lambda e: root.attributes('-fullscreen', False))

    def update():
        if not state['paused']:
            now = time.perf_counter()
            elapsed = now - state['start_time'] - state['total_paused_duration']
            epoch_ms = int(time.time() * 1000)
            ms_val = epoch_ms % 1000000

            state['tick_count'] += 1
            state['fps_tick_count'] += 1

            # Update FPS every 0.5s
            if (now - state['last_fps_calc_time']) >= 0.5:
                state['current_fps'] = state['fps_tick_count'] / (now - state['last_fps_calc_time'])
                state['fps_tick_count'] = 0
                state['last_fps_calc_time'] = now

            # Elapsed formatted mm:ss.mmm
            mins = int(elapsed // 60)
            secs = elapsed % 60
            elapsed_str = f"{mins:02d}:{secs:06.3f}"

            ms_label.config(text=f"{ms_val:06d} ms")
            clock_label.config(text=f"Elapsed: {elapsed_str} | Epoch: {epoch_ms} ms")
            stats_label.config(
                text=f"Tick: #{state['tick_count']:06d} | Rate: {state['current_fps']:.1f} FPS | [Space]: Pause  [R]: Reset  [F11]: Fullscreen"
            )

        if test_mode_ticks is not None:
            if state['tick_count'] >= test_mode_ticks:
                root.destroy()
                return

        # Target ~1ms resolution update
        root.after(1, update)

    update()

    if test_mode_ticks is None:
        root.mainloop()
    else:
        root.mainloop()

    return state


def main():
    parser = argparse.ArgumentParser(description="Latency Stopwatch Benchmark Utility")
    parser.add_argument("--headless", action="store_true", help="Run in headless console mode")
    parser.add_argument("--duration", type=float, default=5.0, help="Duration in seconds for headless mode")
    parser.add_argument("--fullscreen", action="store_true", help="Start GUI in fullscreen mode")
    parser.add_argument("--title", default="Latency Timer - Drag to Secondary Display", help="Window title")
    parser.add_argument("--measure-timer", action="store_true", help="Measure system timer resolution and exit")
    args = parser.parse_args()

    if args.measure_timer:
        res = measure_system_timer_resolution()
        print("System High-Precision Timer Resolution:")
        print(f"  Min: {res['min_resolution_us']:.3f} us")
        print(f"  Avg: {res['avg_resolution_us']:.3f} us")
        print(f"  Max: {res['max_resolution_us']:.3f} us")
        return

    if args.headless:
        run_headless_benchmark(duration=args.duration)
    else:
        create_latency_stopwatch(title=args.title, fullscreen=args.fullscreen)


if __name__ == '__main__':
    main()
