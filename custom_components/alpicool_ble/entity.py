"""Base entity for the Alpicool BLE integration."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlpicoolDeviceUpdateCoordinator


class AlpicoolEntity(CoordinatorEntity[AlpicoolDeviceUpdateCoordinator]):
    """Base class for Alpicool entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AlpicoolDeviceUpdateCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._address = coordinator.address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=f"Alpicool {self._address}",
            manufacturer="Alpicool",
        )

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        return super().available and self.coordinator.data is not None
