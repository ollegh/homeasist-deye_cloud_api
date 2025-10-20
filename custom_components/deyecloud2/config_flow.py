from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
import aiohttp
import hashlib

from . import (
    DOMAIN, 
    CONF_SCAN_INTERVAL,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_DEVICE_SN,
    CONF_SERVER,
    CONF_MODE,
    CONF_URL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    SERVER_EU,
    SERVER_US,
    MODE_API,
    MODE_DEYE_DIRECT,
)


class DeyeCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        if user_input is None:
            schema = vol.Schema({
                vol.Required(CONF_MODE, default=MODE_DEYE_DIRECT): vol.In({
                    MODE_DEYE_DIRECT: "Deye Cloud Direct",
                    MODE_API: "API Endpoint",
                })
            })
            return self.async_show_form(step_id="user", data_schema=schema)

        if user_input[CONF_MODE] == MODE_API:
            return await self.async_step_api()
        return await self.async_step_deye()

    async def async_step_api(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            if not user_input.get(CONF_URL):
                errors["base"] = "invalid_url"
            else:
                return self.async_create_entry(
                    title="Deye Cloud 2 (API)",
                    data={CONF_MODE: MODE_API, **user_input},
                )

        schema = vol.Schema({
            vol.Required(CONF_URL): str,
            vol.Optional(CONF_TOKEN): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                vol.Coerce(int), vol.Range(min=5, max=3600)
            ),
        })
        return self.async_show_form(step_id="api", data_schema=schema, errors=errors)

    async def async_step_deye(self, user_input=None) -> FlowResult:
        errors = {}
        
        if user_input is not None:
            # Validate configuration
            try:
                await self._validate_config(user_input)
                await self.async_set_unique_id(f"deye_{user_input[CONF_EMAIL]}_{user_input[CONF_DEVICE_SN]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Deye Cloud 2 (Direct)", 
                    data={CONF_MODE: MODE_DEYE_DIRECT, **user_input}
                )
            except Exception as err:
                errors["base"] = str(err)

        schema = vol.Schema({
            vol.Required(CONF_APP_ID): str,
            vol.Required(CONF_APP_SECRET): str,
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_DEVICE_SN): str,
            vol.Required(CONF_SERVER, default=SERVER_EU): vol.In({
                SERVER_EU: "Europe (EU1)",
                SERVER_US: "United States (US1)"
            }),
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                vol.Coerce(int), vol.Range(min=10, max=3600)
            ),
        })
        return self.async_show_form(step_id="deye", data_schema=schema, errors=errors)

    async def _validate_config(self, config: dict) -> None:
        """Validate configuration by testing API connection"""
        server = config[CONF_SERVER]
        url = f"https://{server}-developer.deyecloud.com/v1.0/account/token"
        
        # Hash password
        password_hash = hashlib.sha256(config[CONF_PASSWORD].encode()).hexdigest()
        
        # Build query parameters
        params = {"appId": config[CONF_APP_ID]}
        
        # Request body
        data = {
            "appSecret": config[CONF_APP_SECRET],
            "email": config[CONF_EMAIL],
            "password": password_hash,
        }
        
        headers = {
            "Content-Type": "application/json",
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params, json=data, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise ValueError(f"Authentication failed: HTTP {resp.status}: {text}")
                    
                    result = await resp.json()
                    if not result.get("success"):
                        raise ValueError(f"Authentication failed: {result.get('msg', 'Unknown error')}")
                    
                    if "accessToken" not in result:
                        raise ValueError("No access token received")
                        
        except aiohttp.ClientError as err:
            raise ValueError(f"Network error: {err}") from err


