from __future__ import annotations

from types import SimpleNamespace

import pytest

from serial_debug_assistant.ui.wave_tab import CTRL_MASK, WaveformTab


class _Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _I18n:
    @staticmethod
    def translate_text(text: str) -> str:
        return text

    @staticmethod
    def format_text(text: str, **values) -> str:
        return text.format(**values)


def _viewport_tab() -> WaveformTab:
    tab = object.__new__(WaveformTab)
    tab.i18n = _I18n()
    tab.window_var = _Variable("自定义")
    tab.custom_window_var = _Variable("12")
    tab.pause_button_text = _Variable("暂停显示")
    tab.view_var = _Variable("")
    tab._custom_window_seconds = 12.0
    tab._selected_window_key = "自定义"
    tab._updating_window_var = False
    tab._paused_view = False
    tab._manual_range = None
    tab._manual_y_range = None
    tab._frozen_x_range = None
    tab._frozen_y_range = None
    tab._unseen_sample_count = 0
    return tab


def test_custom_window_follows_latest_timestamp() -> None:
    tab = _viewport_tab()

    assert tab._resolve_x_range(0.0, 100.0) == pytest.approx((88.0, 100.0))

    tab._custom_window_seconds = 5.5
    assert tab._resolve_x_range(0.0, 103.0) == pytest.approx((97.5, 103.0))


def test_custom_window_minimum_is_ten_milliseconds() -> None:
    tab = _viewport_tab()

    tab._set_custom_window_span(0.001, switch_option=False)

    assert tab._custom_window_seconds == pytest.approx(0.01)
    assert tab.custom_window_var.get() == "0.01"


def test_history_window_stays_fixed_when_new_data_arrives() -> None:
    tab = _viewport_tab()
    tab._paused_view = True
    tab._manual_range = (10.0, 20.0)
    tab._frozen_x_range = (10.0, 20.0)
    tab._x_range = (10.0, 20.0)
    tab.series_data = {"VOLTAGE": []}
    tab._series_timestamps = {}
    tab._series_timestamp_lengths = {}
    tab.latest_values = {}
    tab._has_unsaved_changes = False
    calls = {"save": 0, "list": 0, "latest": 0, "redraw": 0}
    tab._append_realtime_batch = lambda _batch, _timestamp: calls.__setitem__("save", calls["save"] + 1)
    tab._queue_list_refresh = lambda: calls.__setitem__("list", calls["list"] + 1)
    tab._queue_latest_refresh = lambda: calls.__setitem__("latest", calls["latest"] + 1)
    tab._queue_redraw = lambda: calls.__setitem__("redraw", calls["redraw"] + 1)

    tab.append_batch({"VOLTAGE": 123.5}, batch_time=21.0)

    assert tab.series_data["VOLTAGE"] == [(21.0, 123.5)]
    assert tab.latest_values["VOLTAGE"] == "123.5"
    assert tab._unseen_sample_count == 1
    assert calls == {"save": 1, "list": 1, "latest": 1, "redraw": 0}
    assert tab._resolve_x_range(0.0, 21.0) == pytest.approx((10.0, 20.0))


def test_vertical_adjustment_does_not_leave_live_follow() -> None:
    tab = _viewport_tab()
    tab._plot_bounds = (0.0, 0.0, 100.0, 100.0)
    tab._x_range = (90.0, 100.0)
    tab._y_range = (0.0, 10.0)
    redraws: list[bool] = []
    tab._queue_redraw = lambda: redraws.append(True)
    event = SimpleNamespace(x=50, y=50, delta=-120, state=CTRL_MASK)

    tab._on_mousewheel(event)

    assert tab._paused_view is False
    assert tab._manual_y_range == pytest.approx((1.2, 11.2))
    assert redraws == [True]


def test_back_to_live_keeps_current_history_span_as_custom_window() -> None:
    tab = _viewport_tab()
    tab._paused_view = True
    tab._x_range = (40.0, 47.25)
    redraws: list[bool] = []
    tab._queue_redraw = lambda: redraws.append(True)

    tab.back_to_live()

    assert tab._paused_view is False
    assert tab._custom_window_seconds == pytest.approx(7.25)
    assert tab.window_var.get() == "自定义"
    assert tab._manual_range is None
    assert redraws == [True]


@pytest.mark.parametrize(
    "selection, expected_paused, expected_range",
    [
        ((50.0, 100.0), False, None),
        ((0.0, 50.0), True, (90.0, 95.0)),
    ],
)
def test_rectangle_zoom_follows_latest_only_when_selection_reaches_right_edge(
    selection: tuple[float, float],
    expected_paused: bool,
    expected_range: tuple[float, float] | None,
) -> None:
    tab = _viewport_tab()
    tab._plot_bounds = (0.0, 0.0, 100.0, 100.0)
    tab._x_range = (90.0, 100.0)
    tab._y_range = (0.0, 10.0)
    tab._zoom_rect_start = (selection[0], 0.0)
    tab._zoom_rect_end = (selection[1], 100.0)
    tab._drag_started_live = True

    tab._apply_rect_zoom()

    assert tab._paused_view is expected_paused
    assert tab._frozen_x_range == expected_range
    assert tab._custom_window_seconds == pytest.approx(5.0)
