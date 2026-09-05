from types import SimpleNamespace
import tkinter as tk
from unittest.mock import Mock

import pytest

from serial_debug_assistant.i18n import I18nManager
from serial_debug_assistant.ui.wave_tab import WaveformTab


def process_redraws(wave):
    done = tk.BooleanVar(wave, value=False)
    wave.after(80, lambda: done.set(True))
    wave.wait_variable(done)


@pytest.fixture(scope="module")
def root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def wave(root, tmp_path, monkeypatch):
    try:
        tab = WaveformTab(
            root, on_apply_period=lambda: None, on_toggle_run=lambda: None,
            on_clear=lambda: None, export_dir=tmp_path,
            on_status=lambda *args: None, i18n=I18nManager(),
        )
        monkeypatch.setattr(tab.canvas, "winfo_width", lambda: 800)
        monkeypatch.setattr(tab.canvas, "winfo_height", lambda: 400)
        monkeypatch.setattr(tab, "_append_realtime_batch", Mock())
        tab.set_time_axis_mode("simulation")
        tab.set_selected_parameters(["VOLTAGE"])
        tab.visible_names.add("VOLTAGE")
        for timestamp in range(41):
            tab.append_batch({"VOLTAGE": float(timestamp)}, batch_time=float(timestamp))
        process_redraws(tab)
        yield tab
    finally:
        for job in root.tk.call("after", "info"):
            tab.after_cancel(job)
        tab.destroy()


def panel_text(wave):
    return [" = ".join(wave.reference_tree.item(item, "values"))
            for item in wave.reference_tree.get_children()]


def test_panel_visible_without_alt_and_survives_pause_and_leave(wave):
    assert wave._alt_pressed is False
    assert "VOLTAGE = 40" in panel_text(wave)
    wave.toggle_pause_view()
    wave.redraw()
    x_range = wave._x_range
    wave._on_canvas_leave(SimpleNamespace())
    wave._update_hover_from_canvas_position(-10, -10)
    wave.redraw()
    assert "VOLTAGE = 40" in panel_text(wave)
    wave.append_batch({"VOLTAGE": 50.0}, batch_time=50.0)
    wave.redraw()
    assert wave._x_range == x_range
    assert "VOLTAGE = 40" in panel_text(wave)
    wave._append_realtime_batch.assert_called_with({"VOLTAGE": 50.0}, 50.0)
    left, top, right, bottom = wave._plot_bounds
    wave._on_canvas_motion(SimpleNamespace(x=(left + right) / 2, y=(top + bottom) / 2, state=0))
    process_redraws(wave)
    assert wave._paused_view is True
    assert "VOLTAGE = 25" in panel_text(wave)
    wave.toggle_pause_view()
    process_redraws(wave)
    assert wave._paused_view is False
    assert "VOLTAGE = 35" in panel_text(wave)


def test_stationary_pointer_tracks_new_samples_without_pausing(wave):
    left, top, right, bottom = wave._plot_bounds
    x = (left + right) / 2
    wave._on_canvas_motion(SimpleNamespace(x=x, y=(top + bottom) / 2, state=0))
    wave.redraw()
    assert "VOLTAGE = 25" in panel_text(wave)
    for timestamp in range(41, 51):
        wave.append_batch({"VOLTAGE": float(timestamp)}, batch_time=float(timestamp))
    # Process the scheduled redraw without sending any further mouse events.
    assert wave._redraw_job is not None
    process_redraws(wave)
    assert wave._paused_view is False
    assert wave._x_range == pytest.approx((20.0, 50.0))
    assert wave._last_hover_canvas_x == x
    assert "VOLTAGE = 35" in panel_text(wave)
    assert len(wave.series_data["VOLTAGE"]) == 51
    wave._append_realtime_batch.assert_called_with({"VOLTAGE": 50.0}, 50.0)


def test_reference_panel_clears_hidden_data_and_translates_controls(wave):
    wave.visible_names.clear()
    wave.redraw()
    assert wave.reference_tree.get_children() == ()
    wave.i18n.set_language("en")
    wave.refresh_texts()
    assert wave.reference_tree.heading("name", "text") == wave.i18n.translate_text("参数名称")
    assert wave.reference_menu.entrycget(0, "label") == wave.i18n.translate_text("水平参考线 H")
    assert wave.reference_button.cget("text") == "Reference lines"


def split_wave(wave):
    first = wave._active_plot
    wave.set_selected_parameters(["VOLTAGE", "CURRENT"])
    wave.visible_names.add("CURRENT")
    wave.series_data["CURRENT"] = [(float(i), 1000.0 + i) for i in range(41)]
    second = wave.add_plot_window()
    wave.move_parameter_to_plot("CURRENT", second)
    wave.redraw()
    return first, second


def test_windows_have_independent_scales_and_share_recording(wave):
    first, second = split_wave(wave)
    assert wave._visible_plot_names() == ["CURRENT"]
    assert wave._y_range[0] > 900
    wave._select_plot(first)
    assert wave._visible_plot_names() == ["VOLTAGE"]
    assert set(wave._latest_widgets) == {"VOLTAGE", "CURRENT"}
    assert wave._y_range[1] < 100
    voltage = wave.series_data["VOLTAGE"]
    wave.append_batch({"VOLTAGE": 50.0, "CURRENT": 1050.0}, batch_time=50.0)
    process_redraws(wave)
    assert wave.series_data["VOLTAGE"] is voltage
    assert wave._x_range == pytest.approx((20.0, 50.0))
    wave._select_plot(second)
    assert set(wave._latest_widgets) == {"VOLTAGE", "CURRENT"}
    assert wave._x_range == pytest.approx((20.0, 50.0))
    assert wave._cached_visible_series["CURRENT"][-1] == (50.0, 1050.0)
    wave._append_realtime_batch.assert_called_with({"VOLTAGE": 50.0, "CURRENT": 1050.0}, 50.0)
    assert not wave._paused_view


def test_parameter_drag_move_cancel_and_click(wave, monkeypatch):
    first = wave._active_plot
    second = wave.add_plot_window()
    source = wave._row_widgets["VOLTAGE"][2]
    start = SimpleNamespace(widget=source, x_root=0, y_root=0)
    end = SimpleNamespace(widget=source, x_root=100, y_root=100)
    monkeypatch.setattr(wave, "_plot_at", lambda x, y: second)
    wave._start_parameter_drag(start, "VOLTAGE")
    wave._finish_parameter_drag(start)
    assert wave._plot_assignments["VOLTAGE"] == first.number
    wave._start_parameter_drag(start, "VOLTAGE")
    wave._move_parameter_drag(end)
    wave._finish_parameter_drag(end)
    process_redraws(wave)
    assert wave._plot_assignments["VOLTAGE"] == second.number
    assert wave._active_plot is second
    assert "VOLTAGE = 40" in panel_text(wave)
    monkeypatch.setattr(wave, "_plot_at", lambda x, y: None)
    wave._start_parameter_drag(start, "VOLTAGE")
    wave._move_parameter_drag(end)
    wave._finish_parameter_drag(end)
    assert wave._plot_assignments["VOLTAGE"] == second.number
    assert wave._parameter_drag is None


def test_closing_all_windows_preserves_samples_and_can_reopen(wave):
    first, second = split_wave(wave)
    data = wave.series_data
    wave.close_plot_window(second)
    assert wave._plot_assignments["CURRENT"] == first.number
    wave.close_plot_window(first)
    process_redraws(wave)
    assert not wave._plot_windows
    assert wave.reference_tree.get_children() == ()
    wave.append_batch({"VOLTAGE": 55.0}, batch_time=55.0)
    process_redraws(wave)
    third = wave.add_plot_window()
    process_redraws(wave)
    assert wave.series_data is data
    assert wave.series_data["VOLTAGE"][-1] == (55.0, 55.0)
    assert wave._plot_assignments == {"VOLTAGE": third.number, "CURRENT": third.number}


def test_pause_and_axis_state_survive_window_switch(wave):
    first, second = split_wave(wave)
    wave._manual_y_range = (1000.0, 1100.0)
    wave.redraw()
    wave.toggle_pause_view()
    wave._select_plot(first)
    assert wave._manual_y_range is None
    assert wave._frozen_y_range[1] < 100
    wave.append_batch({"VOLTAGE": 80.0, "CURRENT": 1080.0}, batch_time=80.0)
    wave.redraw()
    assert wave._x_range == pytest.approx((10.0, 40.0))
    wave._select_plot(second)
    assert wave._manual_y_range == (1000.0, 1100.0)
    assert wave._x_range == pytest.approx((10.0, 40.0))
    wave.show_all()
    wave.redraw()
    for plot in (first, second):
        wave._select_plot(plot)
        assert wave._manual_y_range is None


def test_clear_resets_every_window_without_removing_layout(wave):
    first, second = split_wave(wave)
    wave.reference_lines.append(("horizontal", 1000.0))
    wave._select_plot(first)
    wave.reference_lines.append(("horizontal", 10.0))
    wave.clear_plot()
    process_redraws(wave)
    assert len(wave._plot_windows) == 2
    for plot in (first, second):
        wave._select_plot(plot)
        assert not wave.reference_lines
    assert all(not samples for samples in wave.series_data.values())


def test_plot_grid_stays_one_column_at_every_width(wave, monkeypatch):
    for _ in range(3):
        wave.add_plot_window()
    monkeypatch.setattr(wave._plots_canvas, "winfo_width", lambda: 1200)
    monkeypatch.setattr(wave._plots_canvas, "winfo_height", lambda: 800)
    wave._layout_plot_windows()
    process_redraws(wave)
    assert all(plot.frame.winfo_width() >= 1190 for plot in wave._plot_windows)
    assert all(plot.frame.winfo_height() >= 190 for plot in wave._plot_windows)
    assert [plot.frame.grid_info()["row"] for plot in wave._plot_windows] == [0, 1, 2, 3]
    assert all(plot.frame.grid_info()["column"] == 0 for plot in wave._plot_windows)
    monkeypatch.setattr(wave._plots_canvas, "winfo_width", lambda: 600)
    wave._layout_plot_windows()
    process_redraws(wave)
    assert all(plot.frame.winfo_width() >= 590 for plot in wave._plot_windows)
    assert not wave._plots_grid.columnconfigure(1, "uniform")


def test_shared_cursor_uses_one_timestamp_across_rows(wave, monkeypatch):
    first, second = split_wave(wave)
    for plot in (first, second):
        monkeypatch.setattr(plot.canvas, "winfo_width", lambda: 800)
        monkeypatch.setattr(plot.canvas, "winfo_height", lambda: 300)
    wave.redraw()
    wave._select_plot(first)
    left, top, right, bottom = wave._plot_bounds
    wave._on_canvas_motion(SimpleNamespace(x=(left + right) / 2, y=(top + bottom) / 2, state=0))
    process_redraws(wave)
    assert "VOLTAGE = 25" in panel_text(wave)
    assert "CURRENT = 1025" in panel_text(wave)
    for plot in (first, second):
        wave._select_plot(plot)
        assert wave._x_range == (10.0, 40.0)
        assert wave._last_hover_canvas_x == (left + right) / 2
        line = plot.canvas.find_withtag("shared_cursor")
        assert len(line) == 1
        assert plot.canvas.coords(line[0])[0] == (left + right) / 2
    wave.append_batch({"VOLTAGE": 50.0, "CURRENT": 1050.0}, batch_time=50.0)
    process_redraws(wave)
    assert "VOLTAGE = 35" in panel_text(wave)
    assert "CURRENT = 1035" in panel_text(wave)
    wave.toggle_pause_view()
    wave._select_plot(first)
    wave._on_canvas_motion(SimpleNamespace(x=right, y=(top + bottom) / 2, state=0))
    process_redraws(wave)
    assert "VOLTAGE = 50" in panel_text(wave)
    assert "CURRENT = 1050" in panel_text(wave)
    axis_labels = [wave._time_axis_canvas.itemcget(item, "text") for item in wave._time_axis_canvas.find_all()
                   if wave._time_axis_canvas.type(item) == "text"]
    assert len(axis_labels) == 5
    for plot in (first, second):
        assert not any(plot.canvas.itemcget(item, "text") in axis_labels for item in plot.canvas.find_all()
                       if plot.canvas.type(item) == "text")


def test_row_without_samples_does_not_change_shared_time_range(wave):
    first, second = split_wave(wave)
    wave.series_data["CURRENT"] = [(0.0, 1000.0)]
    wave._invalidate_series_cache("CURRENT")
    wave.redraw()
    for plot in (first, second):
        wave._select_plot(plot)
        assert wave._x_range == (10.0, 40.0)
        assert plot.canvas.find_withtag("shared_cursor")
    assert "CURRENT = /" in panel_text(wave)


def test_fixed_vertical_references_are_shared_but_y_references_are_local(wave):
    first, second = split_wave(wave)
    wave._select_plot(first)
    wave.reference_lines.extend([("vertical", 25.0), ("horizontal", 10.0)])
    wave._select_plot(second)
    assert ("vertical", 25.0) in wave._plot_reference_lines()
    assert ("horizontal", 10.0) not in wave._plot_reference_lines()
    wave.clear_reference_lines()
    wave._select_plot(first)
    assert wave._plot_reference_lines() == []


def test_reference_marker_uses_original_samples_after_downsampling(wave):
    wave.series_data["VOLTAGE"] = [(float(i), float(i)) for i in range(10000)]
    wave._invalidate_series_cache("VOLTAGE")
    wave.show_all()
    wave._shared_cursor_ratio = 5002 / 9999
    wave.redraw()
    assert "VOLTAGE = 5002" in panel_text(wave)
    left, top, right, bottom = wave._plot_bounds
    low, high = wave._y_range
    expected_y = wave._value_to_canvas_y(5002.0, top, bottom, low, high)
    dots = [item for item in wave.canvas.find_all() if wave.canvas.type(item) == "oval"]
    coords = wave.canvas.coords(dots[-1])
    assert (coords[1] + coords[3]) / 2 == pytest.approx(expected_y)
