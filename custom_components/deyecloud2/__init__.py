from __future__ import annotations

from datetime import timedelta, datetime
import logging
from typing import Any
import hashlib
import json
import asyncio

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

DOMAIN = "deyecloud2"

# Configuration keys
CONF_MODE = "mode"
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_DEVICE_SN = "device_sn"
CONF_SERVER = "server"

# Servers
SERVER_EU = "eu1"
SERVER_US = "us1"

DEFAULT_SCAN_INTERVAL = 60

PLATFORMS: list[str] = ["sensor", "binary_sensor"]

# Modes
MODE_API = "api"
MODE_DEYE_DIRECT = "deye_direct"

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = aiohttp.ClientSession()

    coordinator = DeyeCloudCoordinator(
        hass,
        session,
        entry.data,
        update_interval=timedelta(seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "session": session,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and data.get("session"):
        await data["session"].close()
    return unload_ok


class DeyeCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Deye Cloud 2 Coordinator",
            update_interval=update_interval,
        )
        self._session = session
        self._config = config
        self._server = config.get(CONF_SERVER, SERVER_EU)
        self._mode = config.get(CONF_MODE, MODE_DEYE_DIRECT)
        
        # Token caching
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        
        # Retry configuration
        self._max_retries = 3
        self._retry_delay = 5  # seconds

    async def _async_update_data(self) -> dict[str, Any]:
        if self._mode == MODE_API:
            return await self._update_from_api_with_retry()
        return await self._update_from_deye_with_retry()

    async def _update_from_api_with_retry(self) -> dict[str, Any]:
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                return await self._update_from_api()
            except Exception as err:
                last_exception = err
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._retry_delay)
        raise UpdateFailed(last_exception) from last_exception

    async def _update_from_api(self) -> dict[str, Any]:
        """Fetch plain-text endpoint and parse as lines with tabs."""
        headers: dict[str, str] = {}
        if self._config.get(CONF_TOKEN):
            headers["Authorization"] = f"Bearer {self._config[CONF_TOKEN]}"
        try:
            async with self._session.get(self._config[CONF_URL], headers=headers, timeout=20) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise UpdateFailed(f"HTTP {resp.status}: {text[:200]}")
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error during API fetch: {err}") from err
        return parse_deyecloud_text(text)

    async def _update_from_deye_with_retry(self) -> dict[str, Any]:
        """Update data with retry logic"""
        last_exception = None
        
        for attempt in range(self._max_retries):
            try:
                _LOGGER.debug(f"Attempting to update data (attempt {attempt + 1}/{self._max_retries})")
                return await self._update_from_deye()
            except Exception as err:
                last_exception = err
                _LOGGER.warning(f"Update attempt {attempt + 1} failed: {err}")
                
                if attempt < self._max_retries - 1:
                    _LOGGER.info(f"Retrying in {self._retry_delay} seconds...")
                    await asyncio.sleep(self._retry_delay)
                else:
                    _LOGGER.error(f"All {self._max_retries} update attempts failed")
        
        raise UpdateFailed(f"Failed to update after {self._max_retries} attempts: {last_exception}") from last_exception

    async def _update_from_deye(self) -> dict[str, Any]:
        """Update data directly from Deye Cloud API"""
        try:
            # Get access token
            token = await self._get_deye_token()
            
            # Get device data
            data = await self._get_deye_device_data(token)
            
            return data
        except Exception as err:
            raise UpdateFailed(err) from err

    async def _get_deye_token(self) -> str:
        """Get access token from Deye Cloud API with caching"""
        # Check if we have a valid cached token
        if (self._access_token and self._token_expires_at and 
            datetime.now() < self._token_expires_at):
            _LOGGER.debug("Using cached access token")
            return self._access_token
        
        _LOGGER.info("Requesting new access token from Deye Cloud API")
        url = f"https://{self._server}-developer.deyecloud.com/v1.0/account/token"
        
        # Hash password
        password_hash = hashlib.sha256(self._config[CONF_PASSWORD].encode()).hexdigest()
        
        # Build query parameters
        params = {"appId": self._config[CONF_APP_ID]}
        
        # Request body
        data = {
            "appSecret": self._config[CONF_APP_SECRET],
            "email": self._config[CONF_EMAIL],
            "password": password_hash,
        }
        
        headers = {
            "Content-Type": "application/json",
        }
        
        try:
            async with self._session.post(url, params=params, json=data, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise UpdateFailed(f"Deye auth failed: HTTP {resp.status}: {text}")
                
                result = await resp.json()
                if not result.get("success"):
                    raise UpdateFailed(f"Deye auth failed: {result.get('msg', 'Unknown error')}")
                
                if "accessToken" not in result:
                    raise UpdateFailed(f"No access token in response: {result}")
                
                # Cache the token (assume 1 hour expiry)
                self._access_token = result["accessToken"]
                self._token_expires_at = datetime.now() + timedelta(hours=1)
                
                _LOGGER.info("Successfully obtained new access token")
                return self._access_token
                
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error during authentication: {err}") from err

    async def _get_deye_device_data(self, token: str) -> dict[str, Any]:
        """Get device data from Deye Cloud API"""
        url = f"https://{self._server}-developer.deyecloud.com/v1.0/device/latest"
        
        data = {
            "deviceList": [self._config[CONF_DEVICE_SN]]
        }
        
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
        }
        
        try:
            async with self._session.post(url, json=data, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise UpdateFailed(f"Deye data failed: HTTP {resp.status}: {text}")
                
                result = await resp.json()
                _LOGGER.debug(f"Received device data: {len(result.get('deviceDataList', []))} devices")
                
                # Convert Deye API response to our format
                return self._convert_deye_response(result)
                
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error during data fetch: {err}") from err

    def _convert_deye_response(self, api_data: dict[str, Any]) -> dict[str, Any]:
        """Convert Deye API response to our internal format"""
        data: dict[str, Any] = {}
        
        # Check if we have device data
        if not api_data.get("deviceDataList") or not api_data["deviceDataList"]:
            _LOGGER.warning("No device data found in API response")
            return data
            
        device_data = api_data["deviceDataList"][0]
        if not device_data.get("dataList"):
            _LOGGER.warning("No data list found in device response")
            return data
        
        _LOGGER.debug(f"Processing {len(device_data['dataList'])} data items")
        
        # Process each data item from the API response
        for item in device_data["dataList"]:
            key_name = item.get("key", "")
            value = item.get("value")
            unit = item.get("unit", "")
            
            if not key_name:
                continue
                
            # Normalize the key for Home Assistant
            normalized_key = normalize_key(key_name)
            
            # Try to convert value to appropriate type
            converted_value: Any
            try:
                if value is None or str(value).lower() in {"nan", "inf", "-inf", "null"}:
                    converted_value = None
                elif isinstance(value, (int, float)):
                    converted_value = value
                elif "." in str(value) or "e" in str(value).lower():
                    converted_value = float(value)
                else:
                    converted_value = int(value)
            except (ValueError, TypeError):
                converted_value = str(value) if value is not None else None
            
            data[normalized_key] = {
                "name": key_name,
                "value": converted_value,
                "unit": unit
            }
        
        # Add device status information
        data["device_online"] = {
            "name": "Device Online",
            "value": True,
            "unit": None
        }
        
        data["last_update"] = {
            "name": "Last Update",
            "value": datetime.now().isoformat(),
            "unit": None
        }
        
        _LOGGER.info(f"Successfully converted {len(data)} data items")
        return data


def normalize_key(name: str) -> str:
    key = name.strip().lower()
    for ch in [" ", "/", "-", "(", ")"]:
        key = key.replace(ch, "_")
    while "__" in key:
        key = key.replace("__", "_")
    return key


def parse_deyecloud_text(raw_text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p for p in line.split("\t") if p != ""]
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        value_str = parts[1].strip()
        unit = parts[2].strip() if len(parts) >= 3 else None

        # Try numeric cast
        value: Any
        try:
            if value_str.lower() in {"nan", "inf", "-inf"}:
                value = None
            elif "." in value_str or "e" in value_str.lower():
                value = float(value_str)
            else:
                value = int(value_str)
        except Exception:
            value = value_str

        key = normalize_key(name)
        data[key] = {"name": name, "value": value, "unit": unit}

    return data


