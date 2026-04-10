# electricaldevices/actuators/solenoid.py

"""Solenoid actuator wrapper built on top of the generic actuator base."""


from nexus import GenericActuator


class Solenoid(GenericActuator):
    """Represent a solenoid actuator with optional inverted logic.

    The class adapts the generic actuator interface into valve-style ``open``
    and ``close`` operations while preserving the externally visible state when
    the underlying hardware logic is inverted.
    """

    def __init__(
        self,
        id: int,
        device_id: str = "Solenoid",
        inverted: bool = False,
        simulated: bool = False,
    ):
        """Initialize the solenoid actuator.

        Args:
            id: Bus or device identifier passed to the generic actuator base.
            device_id: Human-readable or canonical device identifier.
            inverted: Whether actuator truth values should be inverted between
                external valve state and the underlying actuator state.
            simulated: Whether the actuator should operate in simulated mode.
        """
        super().__init__(id=id, device_id=device_id, simulated=simulated)
        self.inverted = inverted

    def setOpen(self, state: bool):
        """Set the externally visible open state of the solenoid.

        Args:
            state: Desired valve-open state. When ``inverted`` is enabled, the
                underlying actuator state is flipped before being passed to
                ``set``.
        """
        self.set(state=state if not self.inverted else not state)

    def open(self):
        """Drive the solenoid to its open state."""
        self.setOpen(True)

    def close(self):
        """Drive the solenoid to its closed state."""
        self.setOpen(False)

    @property
    def state(self):
        """Return the externally visible valve state.

        Returns:
            The logical valve state after applying inversion rules to the
            underlying actuator value.
        """
        return self.value if not self.inverted else (not self.value)
