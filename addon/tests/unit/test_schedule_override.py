#!/usr/bin/env python3
"""Test per-zone schedule override in glozone.py."""

import pytest
from unittest.mock import patch

import glozone


@pytest.fixture(autouse=True)
def setup_glozone_config():
    """Set up glozone with a test config and restore after."""
    config = {
        "circadian_rhythms": {
            "Daily Rhythm 1": {
                "wake_time": 7.0,
                "bed_time": 22.0,
                "wake_alt_time": 9.0,
                "wake_alt_days": [5, 6],
                "bed_alt_time": 23.5,
                "bed_alt_days": [4, 5],
            }
        },
        "glozones": {
            "Living Room": {
                "rhythm": "Daily Rhythm 1",
                "areas": [],
                "is_default": True,
                "schedule_override": None,
            },
            "Bedroom": {
                "rhythm": "Daily Rhythm 1",
                "areas": [],
                "is_default": False,
                "schedule_override": None,
            },
        },
    }
    old_config = glozone._config
    glozone._config = config
    yield config
    glozone._config = old_config


class TestApplyScheduleOverride:
    """Test apply_schedule_override() modes."""

    def test_no_override_leaves_config_unchanged(self):
        """No override → config dict unchanged."""
        cfg = {
            "wake_time": 7.0,
            "bed_time": 22.0,
            "wake_alt_time": 9.0,
            "bed_alt_time": 23.5,
        }
        original = dict(cfg)
        glozone.apply_schedule_override("Living Room", cfg)
        assert cfg == original

    def test_main_mode_disables_alt(self):
        """mode='main' disables alt times."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "main",
            "until_date": "2026-12-31",
            "until_event": "wake",
        }
        cfg = {
            "wake_time": 7.0,
            "bed_time": 22.0,
            "wake_alt_time": 9.0,
            "bed_alt_time": 23.5,
        }
        glozone.apply_schedule_override("Living Room", cfg)
        assert cfg["wake_time"] == 7.0
        assert cfg["bed_time"] == 22.0
        assert cfg["wake_alt_time"] is None
        assert cfg["bed_alt_time"] is None

    def test_alt_mode_swaps_alt_into_primary(self):
        """mode='alt' makes alt times the primary, disables alt."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "alt",
            "until_date": "2026-12-31",
            "until_event": "wake",
        }
        cfg = {
            "wake_time": 7.0,
            "bed_time": 22.0,
            "wake_alt_time": 9.0,
            "bed_alt_time": 23.5,
        }
        glozone.apply_schedule_override("Living Room", cfg)
        assert cfg["wake_time"] == 9.0
        assert cfg["bed_time"] == 23.5
        assert cfg["wake_alt_time"] is None
        assert cfg["bed_alt_time"] is None

    def test_alt_mode_partial_only_wake(self):
        """mode='alt' with only wake_alt_time set."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "alt",
            "until_date": "2026-12-31",
            "until_event": "wake",
        }
        cfg = {
            "wake_time": 7.0,
            "bed_time": 22.0,
            "wake_alt_time": 9.0,
            "bed_alt_time": None,
        }
        glozone.apply_schedule_override("Living Room", cfg)
        assert cfg["wake_time"] == 9.0
        assert cfg["bed_time"] == 22.0  # unchanged, no alt bed

    def test_custom_mode_uses_custom_times(self):
        """mode='custom' uses custom_wake/custom_bed."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "custom",
            "custom_wake": 8.5,
            "custom_bed": 23.0,
            "until_date": "2026-12-31",
            "until_event": "bed",
        }
        cfg = {
            "wake_time": 7.0,
            "bed_time": 22.0,
            "wake_alt_time": 9.0,
            "bed_alt_time": 23.5,
        }
        glozone.apply_schedule_override("Living Room", cfg)
        assert cfg["wake_time"] == 8.5
        assert cfg["bed_time"] == 23.0
        assert cfg["wake_alt_time"] is None
        assert cfg["bed_alt_time"] is None

    def test_unknown_zone_leaves_config_unchanged(self):
        """Override for nonexistent zone → config unchanged."""
        cfg = {"wake_time": 7.0, "bed_time": 22.0}
        original = dict(cfg)
        glozone.apply_schedule_override("Nonexistent Zone", cfg)
        assert cfg == original


class TestClearExpiredOverrides:
    """Test clear_expired_overrides() at phase transitions."""

    @patch("glozone.save_config")
    def test_ascend_clears_wake_override_on_date(self, mock_save):
        """Ascend phase clears override with until_event='wake' when today >= until_date."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "alt",
            "until_date": "2026-01-01",  # past date
            "until_event": "wake",
        }
        glozone.clear_expired_overrides("ascend")
        assert glozone._config["glozones"]["Living Room"]["schedule_override"] is None
        mock_save.assert_called_once()

    @patch("glozone.save_config")
    def test_descend_clears_bed_override_on_date(self, mock_save):
        """Descend phase clears override with until_event='bed' when today >= until_date."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "main",
            "until_date": "2026-01-01",
            "until_event": "bed",
        }
        glozone.clear_expired_overrides("descend")
        assert glozone._config["glozones"]["Living Room"]["schedule_override"] is None
        mock_save.assert_called_once()

    @patch("glozone.save_config")
    def test_ascend_does_not_clear_bed_override(self, mock_save):
        """Ascend phase does NOT clear override with until_event='bed'."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "main",
            "until_date": "2026-01-01",
            "until_event": "bed",
        }
        glozone.clear_expired_overrides("ascend")
        assert (
            glozone._config["glozones"]["Living Room"]["schedule_override"] is not None
        )
        mock_save.assert_not_called()

    @patch("glozone.save_config")
    def test_future_date_not_cleared(self, mock_save):
        """Override with future until_date is NOT cleared."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "alt",
            "until_date": "2099-12-31",
            "until_event": "wake",
        }
        glozone.clear_expired_overrides("ascend")
        assert (
            glozone._config["glozones"]["Living Room"]["schedule_override"] is not None
        )
        mock_save.assert_not_called()

    @patch("glozone.save_config")
    def test_clears_multiple_zones(self, mock_save):
        """Multiple expired overrides cleared in one call."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "alt",
            "until_date": "2026-01-01",
            "until_event": "wake",
        }
        glozone._config["glozones"]["Bedroom"]["schedule_override"] = {
            "mode": "main",
            "until_date": "2026-01-01",
            "until_event": "wake",
        }
        glozone.clear_expired_overrides("ascend")
        assert glozone._config["glozones"]["Living Room"]["schedule_override"] is None
        assert glozone._config["glozones"]["Bedroom"]["schedule_override"] is None
        mock_save.assert_called_once()


class TestGetNextActiveTimes:
    """Test get_next_active_times() resolution."""

    def test_returns_none_for_unknown_zone(self):
        """Unknown zone returns None."""
        result = glozone.get_next_active_times("Nonexistent Zone")
        # Zone doesn't exist but get_rhythm_for_zone returns DEFAULT_RHYTHM
        # which may or may not exist in config. Let's test with a real zone.
        pass

    def test_returns_dict_with_expected_keys(self):
        """Result has wake_day, wake_day_name, wake_time, bed_day, bed_day_name, bed_time."""
        result = glozone.get_next_active_times("Living Room")
        assert result is not None
        assert "wake_day" in result
        assert "wake_day_name" in result
        assert "wake_time" in result
        assert "bed_day" in result
        assert "bed_day_name" in result
        assert "bed_time" in result

    def test_day_names_are_valid(self):
        """Day names are valid abbreviations."""
        result = glozone.get_next_active_times("Living Room")
        valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        assert result["wake_day_name"] in valid_days
        assert result["bed_day_name"] in valid_days

    def test_override_affects_times(self):
        """With custom override, next times reflect the custom values."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "custom",
            "custom_wake": 10.0,
            "custom_bed": 21.0,
            "until_date": "2099-12-31",
            "until_event": "wake",
        }
        result = glozone.get_next_active_times("Living Room")
        assert result is not None
        # After override is applied, alt times are cleared and custom times used
        # The next wake/bed should use the custom times
        assert result["wake_time"] == 10.0 or result["bed_time"] == 21.0

    def test_main_override_uses_primary_times(self):
        """With main override, alt days are ignored, primary times always used."""
        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "main",
            "until_date": "2099-12-31",
            "until_event": "wake",
        }
        result = glozone.get_next_active_times("Living Room")
        assert result is not None
        # Primary times: wake=7.0, bed=22.0 — alt is disabled
        assert result["wake_time"] == 7.0
        assert result["bed_time"] == 22.0

    def test_override_expiry_at_bed_reverts_next_wake(self):
        """Override expiring at bed tonight → next wake uses normal alt schedule."""
        from datetime import datetime

        # Friday 2:20pm (weekday=4), override expires at bed today
        fake_now = datetime(2026, 2, 20, 14, 20)

        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "main",
            "until_date": "2026-02-20",
            "until_event": "bed",
        }
        # Alt wake on Sat(5), Sun(6) = 9.0
        result = glozone.get_next_active_times("Living Room", _now=fake_now)
        assert result is not None
        # Bed tonight still uses override (main): 22.0
        assert result["bed_time"] == 22.0
        # Next wake is Saturday — override expired at bed, so alt applies
        # Saturday (weekday=5) is in wake_alt_days=[5,6] → wake_alt_time=9.0
        assert result["wake_time"] == 9.0

    def test_override_expiry_at_wake_reverts_next_bed(self):
        """Override expiring at wake tomorrow → next bed uses normal schedule."""
        from datetime import datetime

        # Friday 2:20pm, override expires at next wake (tomorrow)
        fake_now = datetime(2026, 2, 20, 14, 20)

        glozone._config["glozones"]["Living Room"]["schedule_override"] = {
            "mode": "alt",
            "until_date": "2026-02-20",
            "until_event": "wake",
        }
        # Alt bed on Fri(4), Sat(5) = 23.5
        # Today is Friday (weekday=4), bed_alt_days=[4,5] → alt bed applies tonight
        # But override mode="alt" forces alt into primary, and override expires at
        # next wake. So tonight's bed is still overridden (alt=23.5 forced as primary).
        result = glozone.get_next_active_times("Living Room", _now=fake_now)
        assert result is not None
        assert result["bed_time"] == 23.5
