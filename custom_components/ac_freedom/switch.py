"""Switch platform for AC Freedom.

Provides independent toggle switches for the AC's feature flags.

The climate entity exposes sleep/health/eco(mildew)/clean as mutually
exclusive presets (for HomeKit compatibility), but on the device they are
independent bits. These switches let each flag be set on its own:

  Local : Display, Health, Self clean, Antifungal (mildew), ECO
  Cloud : Display, Health, Self clean, Antifungal (mildew), ECO

ECO is bit 3 of state byte 20 (command byte 18) in the local protocol and
the "ecomode" parameter of the AUX cloud API.

The display switch keeps its original unique_id so existing entities are
preserved.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .cloud_api.const import (
    AC_CLEAN,
    AC_HEALTH,
    AC_MILDEW_PROOF,
    AC_SCREEN_DISPLAY,
    AUX_ECOMODE,
)
from .const import CONN_CLOUD, CONN_LOCAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# (unique_id suffix, name, icon, local AcState attribute)
LOCAL_FLAGS = [
    ("display", "Display", "mdi:monitor", "display"),
    ("health", "Health", "mdi:heart-outline", "health"),
    ("clean", "Self clean", "mdi:water-sync", "clean"),
    ("mildew", "Antifungal", "mdi:bacteria-outline", "mildew"),
    ("eco", "ECO", "mdi:leaf", "eco"),
]

# (unique_id suffix, name, icon, cloud param key)
CLOUD_FLAGS = [
    ("display", "Display", "mdi:monitor", AC_SCREEN_DISPLAY),
    ("health", "Health", "mdi:heart-outline", AC_HEALTH),
    ("clean", "Self clean", "mdi:water-sync", AC_CLEAN),
    ("mildew", "Antifungal", "mdi:bacteria-outline", AC_MILDEW_PROOF),
    ("eco", "ECO", "mdi:leaf", AUX_ECOMODE),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AC Freedom switches."""
    data = hass.data[DOMAIN][entry.entry_id]
    conn_mode = data.get("mode", CONN_LOCAL)

    entities: list[SwitchEntity] = []

    if conn_mode == CONN_CLOUD:
        coordinator = data["coordinator"]
        for dev in data.get("devices", []):
            for flag in CLOUD_FLAGS:
                entities.append(CloudFlagSwitch(coordinator, dev, *flag))
    else:
        for dev_entry in data.get("local_devices", []):
            for flag in LOCAL_FLAGS:
                entities.append(
                    LocalFlagSwitch(dev_entry["coordinator"], dev_entry["info"], *flag)
                )

    if entities:
        async_add_entities(entities)


class LocalFlagSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for a single feature bit of a local AC."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator, dev_info: dict, key: str, name: str, icon: str, attr: str
    ) -> None:
        super().__init__(coordinator)
        self._api = coordinator.api
        self._flag = attr
        self._attr_name = name
        self._attr_icon = icon
        ip = dev_info[CONF_IP_ADDRESS]
        mac = dev_info.get("mac", "ac")
        self._attr_unique_id = f"{ip}_{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{ip}_{mac}")},
            name=dev_info.get(CONF_NAME, f"AC Freedom ({ip})"),
            manufacturer="AUX",
            model="AC Freedom (Local)",
        )

    @property
    def is_on(self) -> bool:
        return bool(getattr(self._api.state, self._flag, 0))

    async def _set(self, value: int) -> None:
        setattr(self._api.state, self._flag, value)
        await self._api.set_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(0)


class CloudFlagSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for a single parameter of a cloud AC."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator, device: dict, key: str, name: str, icon: str, param: str
    ) -> None:
        super().__init__(coordinator)
        self._device = device
        self._did = device["endpointId"]
        self._cloud_api = coordinator.cloud_api
        self._param = param
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"cloud_{self._did}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._did)},
            name=device.get("friendlyName", "AUX AC"),
            manufacturer="AUX",
            model="AC Freedom (Cloud)",
        )

    def _params(self) -> dict:
        if self.coordinator.data and self._did in self.coordinator.data:
            return self.coordinator.data[self._did].get("params", {})
        return self._device.get("params", {})

    @property
    def is_on(self) -> bool:
        return bool(self._params().get(self._param, 0))

    async def _set(self, value: int) -> None:
        if self.coordinator.data and self._did in self.coordinator.data:
            self._device = self.coordinator.data[self._did]
        await self._cloud_api.set_device_params(self._device, {self._param: value})
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(0)
