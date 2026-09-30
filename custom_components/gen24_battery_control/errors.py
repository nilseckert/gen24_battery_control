"""Transport exceptions shared by the controller and the pymodbus transport."""


class TransportError(Exception):
    """Communication with the inverter failed."""


class WriteRejected(TransportError):
    """The inverter answered a write with a Modbus exception response."""
