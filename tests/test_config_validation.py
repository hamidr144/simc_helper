"""Tests for pydantic config validation (src.core.config)."""

import logging
import os
import sys
from unittest.mock import patch

import pytest

# Ensure the project src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.core.config import Config, get_config, reset_config


class TestConfigDefaults:
    """Test that Config uses correct default values."""

    def test_default_base_dir(self):
        assert Config().base_dir == "."

    def test_default_port(self):
        assert Config().port == 8000

    def test_default_host(self):
        assert Config().host == "127.0.0.1"

    def test_default_admin_token_is_none(self):
        assert Config().admin_token is None

    def test_default_cluster_secret_is_none(self):
        assert Config().cluster_secret is None

    def test_default_master_url(self):
        assert Config().master_url == "http://localhost:8000"

    def test_default_worker_name(self):
        assert Config().worker_name == "LocalWorker"

    def test_default_simc_update_interval(self):
        assert Config().simc_update_interval_seconds == 86400

    def test_default_dev_mode_false(self):
        assert Config().simc_helper_dev_mode is False

    def test_default_cors_enabled_false(self):
        assert Config().cors_enabled is False

    def test_default_sim_cooldown(self):
        assert Config().sim_cooldown_seconds == 300

    def test_default_log_level(self):
        assert Config().log_level == "INFO"


class TestConfigFromEnv:
    """Test that Config reads environment variables correctly."""

    @patch.dict(os.environ, {"PORT": "9999", "HOST": "0.0.0.0", "SIMC_HELPER_DEV_MODE": "1"})
    def test_env_override_port_host(self):
        reset_config()
        config = Config()
        assert config.port == 9999
        assert config.host == "0.0.0.0"

    @patch.dict(os.environ, {"ADMIN_TOKEN": "super-secret"})
    def test_env_override_admin_token(self):
        reset_config()
        config = Config()
        assert config.admin_token == "super-secret"

    @patch.dict(os.environ, {"CLUSTER_SECRET": "my-cluster-secret"})
    def test_env_override_cluster_secret(self):
        reset_config()
        config = Config()
        assert config.cluster_secret == "my-cluster-secret"

    @patch.dict(os.environ, {"MASTER_URL": "http://example.com:8080"})
    def test_env_override_master_url(self):
        reset_config()
        config = Config()
        assert config.master_url == "http://example.com:8080"

    @patch.dict(os.environ, {"SIMC_HELPER_DEV_MODE": "1"})
    def test_dev_mode_enables_cors(self):
        reset_config()
        config = Config()
        assert config.simc_helper_dev_mode is True
        assert config.cors_enabled is True

    @patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": '["http://localhost:3000","http://localhost:8080"]'})
    def test_cors_json_array(self):
        reset_config()
        config = Config()
        assert config.cors_enabled is False  # not dev mode
        assert config.cors_allowed_origins == "http://localhost:3000,http://localhost:8080"

    @patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "http://localhost:3000,http://localhost:8080"})
    def test_cors_csv(self):
        reset_config()
        config = Config()
        assert config.cors_allowed_origins == "http://localhost:3000,http://localhost:8080"

    @patch.dict(os.environ, {"SIMC_HELPER_DEV_MODE": "1", "CORS_ALLOWED_ORIGINS": '["http://localhost:3000"]'})
    def test_dev_mode_cors_enabled(self):
        reset_config()
        config = Config()
        assert config.cors_enabled is True

    @patch.dict(os.environ, {"SIMC_PATH": "/opt/simc/bin/simc"})
    def test_simc_path(self):
        reset_config()
        config = Config()
        assert config.simc_path == "/opt/simc/bin/simc"


class TestConfigValidation:
    """Test config field validation."""

    def test_port_out_of_range_low(self):
        with pytest.raises(Exception):
            Config(port=0)

    def test_port_out_of_range_high(self):
        with pytest.raises(Exception):
            Config(port=65536)

    def test_simc_update_interval_negative(self):
        with pytest.raises(Exception):
            Config(simc_update_interval_seconds=-1)

    def test_log_level_invalid(self):
        with pytest.raises(Exception):
            Config(log_level="VERBOSE")

    def test_valid_log_levels(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cfg = Config(log_level=level)
            assert cfg.log_level == level


class TestGetConfigSingleton:
    """Test the get_config() singleton pattern."""

    def test_get_config_creates_once(self):
        reset_config()
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_reset_config_clears_singleton(self):
        reset_config()
        c1 = get_config()
        reset_config()
        c2 = get_config()
        assert c1 is not c2


class TestProductionWarnings:
    """Test that production mode logs warnings for missing secrets."""

    def test_production_missing_admin_token_logs_warning(self, caplog):
        reset_config()
        with caplog.at_level(logging.WARNING, logger="master"):
            # Clear any previous warnings
            caplog.clear()
            config = Config(simc_helper_dev_mode=False)
            # The config creation should have logged a warning
            warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
            assert any("ADMIN_TOKEN" in m for m in warning_messages)

    def test_production_missing_cluster_secret_logs_warning(self, caplog):
        reset_config()
        with caplog.at_level(logging.WARNING, logger="master"):
            caplog.clear()
            config = Config(simc_helper_dev_mode=False, admin_token="token")
            warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
            assert any("CLUSTER_SECRET" in m for m in warning_messages)

    def test_dev_mode_no_warnings(self, caplog):
        reset_config()
        with caplog.at_level(logging.WARNING, logger="master"):
            caplog.clear()
            config = Config(simc_helper_dev_mode=True)
            warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
            assert not any("ADMIN_TOKEN" in m or "CLUSTER_SECRET" in m for m in warning_messages)
