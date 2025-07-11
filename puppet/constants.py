"""
Core constants and enums for the Puppeteer communication system.

This has a few network related constants. It also has enums used
for input, callbacks, rotation, and more.
"""


import enum


# Network configuration constants
#: Port used for UDP broadcast discovery
BROADCAST_PORT = 43842
#: Magic bytes used to identify Puppeteer broadcast packets
BROADCAST_MAGIC_NUMBER = b"PUPPETEER"


class CallbackType(enum.Enum):
    """
    The named Puppeteer callback varieties.
    """
    BARITONE = "BARITONE"
    PLAYER_POSITION = "PLAYER_POSITION"
    PLAYER_YAW = "PLAYER_YAW"
    PLAYER_PITCH = "PLAYER_PITCH"
    PLAYER_DAMAGE = "PLAYER_DAMAGE"
    PLAYER_DEATH = "PLAYER_DEATH"
    PLAYER_INVENTORY = "PLAYER_INVENTORY"
    CHAT = "CHAT"
    OPEN_SCREEN = "OPEN_SCREEN"
    SET_CONTAINER_CONTENTS = "SET_CONTAINER_CONTENTS"
    SET_CONTAINER_PROPERTIES = "SET_CONTAINER_PROPERTIES"
    CLOSE_CONTAINER = "CLOSE_CONTAINER"
    SET_CURSOR_ITEM = "SET_CURSOR_ITEM"
class SlotActionType(enum.Enum):
    """
    NOTE: This is taken from Yarn, so it might change from version to version
    """
    PICKUP = "PICKUP"          # raw id 0
    QUICK_MOVE = "QUICK_MOVE"  # raw id 1
    SWAP = "SWAP"              # raw id 2
    CLONE = "CLONE"            # raw id 3
    THROW = "THROW"            # raw id 4
    QUICK_CRAFT = "QUICK_CRAFT"# raw id 5
    PICKUP_ALL = "PICKUP_ALL"  # raw id 6

class PacketCallbackState(enum.Enum):
    """
    How packet callback states are handled.

    When a packet is set to notify, it only tells you _that_ a packet is sent, and not any
    additional information.

    When a packet is set to "network serialized" the structure is similar to the protocol
    as described in the wiki, meaning all packet types are supported, but difficult to make
    use of. See: https://minecraft.wiki/w/Java_Edition_protocol/Packets

    When a packet is set to "object serialized" the structure is similar to how it is represented
    internally. This mode is typically easier to use, often just key-value data structures. However,
    is simply unusable for many packet types, due to complex internal data structures.

    **Note** that in this mode keys are taken from the Yarn mappings used during the mods compilation,
    meaning that it is subject to change, even if the Minecraft version number is the exact same.

    ====================================================================================

    You can optimally set a packet type to "next" meaning you only receive the next packet.


    """
    DISABLED = "DISABLED"

    NOTIFY_ONLY = "NOTIFY_ONLY"
    NOTIFY_NEXT = "NOTIFY_NEXT"

    NETWORK_SERIALIZED = "NETWORK_SERIALIZED"
    NETWORK_SERIALIZED_NEXT = "NETWORK_SERIALIZED_NEXT"

    OBJECT_SERIALIZED = "OBJECT_SERIALIZED"
    OBJECT_SERIALIZED_NEXT = "OBJECT_SERIALIZED_NEXT"

class Direction(enum.Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"

    EAST = "EAST"
    WEST = "WEST"

    UP = "UP"
    DOWN = "DOWN"



class InputButton(enum.Enum):
    """
    Input types that you can override and force the state of.
    """

    FORWARDS = "forwards"
    BACKWARDS = "backwards"
    LEFT = "left"
    RIGHT = "right"
    JUMP = "jump"
    SNEAK = "sneak"
    SPRINT = "sprint"

    ATTACK = "attack"
    USE = "use"


string_callback_dict = {
    v.value: v for k, v in CallbackType.__members__.items()
}
string_packet_state_dict = {
    v.value: v for k, v in PacketCallbackState.__members__.items()
}



class RoMethod(enum.Enum):
    """
    Rotation interpolation methods used in algorithmic rotation
    """
    LINEAR = "linear"  # Linear interpolation
    SINE = "sine"  # Ease-in using sine curve
    QUADRATIC_IN = "quadraticIn"  # Ease-in (accelerating from zero velocity, t^2)
    CUBIC_IN = "cubicIn"  # Ease-in (t^3)
    QUARTIC_IN = "quarticIn"  # Ease-in (t^4)
    QUINTIC_IN = "quinticIn"  # Ease-in (t^5)
    SEXTIC_IN = "sexticIn"  # Ease-in (t^6)
    QUADRATIC_OUT = "quadraticOut"  # Ease-out (decelerating to zero velocity, 1-(1-t)^2)
    CUBIC_OUT = "cubicOut"  # Ease-out (1-(1-t)^3)
    QUARTIC_OUT = "quarticOut"  # Ease-out (1-(1-t)^4)
    QUINTIC_OUT = "quinticOut"  # Ease-out (1-(1-t)^5)
    SINE_IN_OUT = "sineInOut"  # Ease-in-out using sine curve
    QUADRATIC_IN_OUT = "quadraticInOut"  # Ease-in-out (smooth start and end, quadratic)
    CUBIC_IN_OUT = "cubicInOut"  # Ease-in-out (cubic)
    QUARTIC_IN_OUT = "quarticInOut"  # Ease-in-out (quartic)
    QUINTIC_IN_OUT = "quinticInOut"  # Ease-in-out (quintic)
    EXPONENTIAL_IN = "exponentialIn"  # Exponential ease-in
    EXPONENTIAL_OUT = "exponentialOut"  # Exponential ease-out
    EXPONENTIAL_IN_OUT = "exponentialInOut"  # Exponential ease-in-out
    ELASTIC_OUT = "elasticOut"  # Elastic ease-out (spring-like, bouncy)

    # Only is supported by auto_use and auto_place
    INSTANT = "instant"


class PuppeteerErrorType(enum.Enum):
    """
    Puppeteer error types.

    Note: These can occur somewhat randomly.
          Assume all functions **CAN AND WILL**
          throw exceptions at **any moment**.
          In addition, can do so in the background.
    """

    UNKNOWN_ERROR = enum.auto()
    SERVER_KILLED = enum.auto()

    FORMAT_ERROR = enum.auto()
    EXPECTED_ARGUMENT_ERROR = enum.auto()
    UNEXPECTED_ARGUMENT_ERROR = enum.auto()

    CONFIG_FILE_ERROR = enum.auto()
    UNKNOWN_MOD = enum.auto()
    UNKNOWN_CONFIG_VALUE_ERROR = enum.auto()
    CONNECTION_ERROR = enum.auto()
    WORLD_JOIN_ERROR = enum.auto()
    MOD_REQUIREMENT_ERROR = enum.auto()
    INTERNAL_EXCEPTION = enum.auto()
    BARITONE_ERROR = enum.auto()


# Forcefully bring them into global scope
# Effectively:
# from PuppeteerErrorType import *
globals().update(PuppeteerErrorType.__members__)

error_str_to_enum = {
    "expected argument":     PuppeteerErrorType .EXPECTED_ARGUMENT_ERROR,
    "unexpected argument":   PuppeteerErrorType .UNEXPECTED_ARGUMENT_ERROR,
    "config file missing":   PuppeteerErrorType .CONFIG_FILE_ERROR,
    "unknown mod":           PuppeteerErrorType .UNKNOWN_MOD,
    "cannot connect":        PuppeteerErrorType .CONNECTION_ERROR,
    "cannot join world":     PuppeteerErrorType .WORLD_JOIN_ERROR,
    "format":                PuppeteerErrorType .FORMAT_ERROR,
    "mod requirement":       PuppeteerErrorType .MOD_REQUIREMENT_ERROR,
    "exception":             PuppeteerErrorType .INTERNAL_EXCEPTION,
    "baritone calculation":  PuppeteerErrorType .BARITONE_ERROR,
    "unknown config item":   PuppeteerErrorType .UNKNOWN_CONFIG_VALUE_ERROR
}


def str2error(error: str) -> PuppeteerErrorType:
    return error_str_to_enum.get(error, PuppeteerErrorType.UNKNOWN_ERROR)
