# -*- coding: utf-8 -*-
"""Tests for crons models, specifically the _crontab_dow_to_name function."""

from copaw.app.crons.models import _crontab_dow_to_name, ScheduleSpec


class TestCrontabDowToName:
    """Test the _crontab_dow_to_name function with various inputs."""

    def test_star_passes_through(self):
        assert _crontab_dow_to_name("*") == "*"

    def test_single_number(self):
        assert _crontab_dow_to_name("1") == "mon"
        assert _crontab_dow_to_name("0") == "sun"
        assert _crontab_dow_to_name("6") == "sat"

    def test_range(self):
        assert _crontab_dow_to_name("1-5") == "mon-fri"
        assert _crontab_dow_to_name("0-6") == "sun-sat"

    def test_step_with_range(self):
        assert _crontab_dow_to_name("1-5/2") == "mon-fri/2"
        assert _crontab_dow_to_name("0-6/3") == "sun-sat/3"

    def test_step_with_single(self):
        assert _crontab_dow_to_name("*/2") == "*/2"
        assert _crontab_dow_to_name("1/2") == "mon/2"

    def test_comma_separated(self):
        assert _crontab_dow_to_name("1,3,5") == "mon,wed,fri"

    def test_comma_separated_with_step(self):
        assert _crontab_dow_to_name("1-5/2,6") == "mon-fri/2,sat"

    def test_already_named(self):
        assert _crontab_dow_to_name("mon") == "mon"
        assert _crontab_dow_to_name("mon-fri") == "mon-fri"
        assert _crontab_dow_to_name("mon,wed,fri") == "mon,wed,fri"


class TestScheduleSpec:
    """Test ScheduleSpec validation with complex cron expressions."""

    def test_complex_cron_with_step_in_hour(self):
        spec = ScheduleSpec(cron="15 9-20/2 * * *")
        assert spec.cron == "15 9-20/2 * * *"

    def test_complex_cron_with_step_in_dow(self):
        spec = ScheduleSpec(cron="0 9 * * 1-5/2")
        assert spec.cron == "0 9 * * mon-fri/2"

    def test_simple_cron_normalization(self):
        spec = ScheduleSpec(cron="0 9 * * 1")
        assert spec.cron == "0 9 * * mon"

    def test_simple_range_normalization(self):
        spec = ScheduleSpec(cron="0 9 * * 1-5")
        assert spec.cron == "0 9 * * mon-fri"
