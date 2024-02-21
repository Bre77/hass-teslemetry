"""Select platform for Teslemetry integration."""
from __future__ import annotations
from itertools import chain
from tesla_fleet_api.const import Scope, Seat, EnergyExportMode, EnergyOperationMode

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TeslemetrySeatHeaterOptions
from .entity import (
    TeslemetryVehicleEntity,
    TeslemetryEnergyInfoEntity,
)
from .models import TeslemetryEnergyData, TeslemetryVehicleData


@dataclass(frozen=True, kw_only=True)
class SeatHeaterDescription(SelectEntityDescription):
    position: Seat
    avaliable_fn: callable


SEAT_HEATER_DESCRIPTIONS: tuple[SeatHeaterDescription, ...] = (
    SeatHeaterDescription(
        key="climate_state_seat_heater_left",
        position=Seat.FRONT_LEFT,
        avaliable_fn=lambda _: True,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_right",
        position=Seat.FRONT_RIGHT,
        avaliable_fn=lambda _: True,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_left",
        position=Seat.REAR_LEFT,
        avaliable_fn=lambda self: not self.exactly(
            "vehicle_config_rear_seat_heaters", 0
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_center",
        position=Seat.REAR_CENTER,
        avaliable_fn=lambda self: not self.exactly(
            "vehicle_config_rear_seat_heaters", 0
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_rear_right",
        position=Seat.REAR_RIGHT,
        avaliable_fn=lambda self: not self.exactly(
            "vehicle_config_rear_seat_heaters", 0
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_third_row_left",
        position=Seat.THIRD_LEFT,
        avaliable_fn=lambda self: not self.exactly(
            "vehicle_config_third_row_seats", "None"
        ),
        entity_registry_enabled_default=False,
    ),
    SeatHeaterDescription(
        key="climate_state_seat_heater_third_row_right",
        position=Seat.THIRD_RIGHT,
        avaliable_fn=lambda self: not self.exactly(
            "vehicle_config_third_row_seats", "None"
        ),
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry select platform from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    scoped = Scope.VEHICLE_CMDS in data.scopes

    async_add_entities(
        chain(
            (
                TeslemetrySeatHeaterSelectEntity(vehicle, description, scoped)
                for description in SEAT_HEATER_DESCRIPTIONS
                for vehicle in data.vehicles
            ),
            (
                TeslemetryOperationSelectEntity(energysite, data.scopes)
                for energysite in data.energysites
                if energysite.info_coordinator.data.get("components_battery")
            ),
            (
                TeslemetryExportRuleSelectEntity(energysite, data.scopes)
                for energysite in data.energysites
                if energysite.info_coordinator.data.get("components_battery")
                and energysite.info_coordinator.data.get("components_solar")
            ),
        )
    )


class TeslemetrySeatHeaterSelectEntity(TeslemetryVehicleEntity, SelectEntity):
    """Select entity for vehicle seat heater."""

    entity_description: SeatHeaterDescription

    _attr_options = [
        TeslemetrySeatHeaterOptions.OFF,
        TeslemetrySeatHeaterOptions.LOW,
        TeslemetrySeatHeaterOptions.MEDIUM,
        TeslemetrySeatHeaterOptions.HIGH,
    ]

    def __init__(
        self,
        data: TeslemetryVehicleData,
        description: SeatHeaterDescription,
        scoped: bool,
    ) -> None:
        """Initialize the vehicle seat select entity."""
        super().__init__(data, description.key)
        self.entity_description = description
        self.scoped = scoped
        self._update()

    def _update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_available = self.entity_description.avaliable_fn(self)
        value = self.get()
        if value is None:
            self._attr_current_option = None
        else:
            self._attr_current_option = self._attr_options[value]

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update()
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.wake_up_if_asleep()
        level = self._attr_options.index(option)
        # AC must be on to turn on seat heater
        if not self.get("climate_state_is_climate_on"):
            await self.handle_command(self.api.auto_conditioning_start())
        await self.handle_command(
            self.api.remote_seat_heater_request(self.description.position, level)
        )
        self.set((self.key, level))


class TeslemetryOperationSelectEntity(TeslemetryEnergyInfoEntity, SelectEntity):
    """Select entity for operation mode select entities."""

    _attr_options: list[str] = [
        EnergyOperationMode.AUTONOMOUS,
        EnergyOperationMode.BACKUP,
        EnergyOperationMode.SELF_CONSUMPTION,
    ]

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the operation mode select entity."""
        super().__init__(data, "default_real_mode")
        self.scoped = Scope.ENERGY_CMDS in scopes

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.get()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.handle_command(self.api.operation(option))
        self.set((self.key, option))


class TeslemetryExportRuleSelectEntity(TeslemetryEnergyInfoEntity, SelectEntity):
    """Select entity for export rules select entities."""

    _attr_options: list[str] = [
        EnergyExportMode.NEVER,
        EnergyExportMode.BATTERY_OK,
        EnergyExportMode.PV_ONLY,
    ]

    def __init__(
        self,
        data: TeslemetryEnergyData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the operation mode select entity."""
        super().__init__(data, "components_customer_preferred_export_rule")
        self.scoped = Scope.ENERGY_CMDS in scopes

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.get(self.key, EnergyExportMode.NEVER)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self.raise_for_scope()
        await self.handle_command(
            self.api.grid_import_export(customer_preferred_export_rule=option)
        )
        self.set((self.key, option))
