from .connection import *
from .world import Chunk
import asyncio

from io import BytesIO
from functools import partial

_MOD_INTEGRATIONS = (
    ("dump itemscroller config", "get itemscroller config item", "set itemscroller config item", "exec itemscroller config item"),
    ("dump litematica config", "get litematica config item", "set litematica config item", "exec litematica config item"),
    ("dump tweakeroo config", "get tweakeroo config item", "set tweakeroo config item", "exec tweakeroo config item"),
    ("dump malilib config", "get malilib config item", "set malilib config item", "exec malilib config item"),
    ("dump minihud config", "get minihud config item", "set minihud config item", "exec minihud config item"),
)

class Player:
    """ Main wrapper class around the connection. """

    # =========================
    #   Connection Management
    # =========================

    async def _callback_handler(self, info):
        print(info)

    def __init__(self, connection: ClientConnection):
        self.connection = connection
        self.connection.callback_handler = self._callback_handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.connection.__aexit__(exc_type, exc, tb)

    @classmethod
    async def discover(cls, with_name=None):
        async for broadcast, (host, _) in gen_broadcasts():
            if with_name is not None and broadcast["player username"] != with_name:
                continue

            connection = ClientConnection(host, broadcast["port"])
            await connection.start()
            return cls(connection)

        assert False, "Unreachable"

    # =========================
    #   Packet Handling
    # =========================

    def _handle_json(self, packet_type: int, json: dict) -> dict:
        assert packet_type == ord('j')
        if json.get("status") == "error":
            raise PuppeteerError(
                "Error: " + json.get("message", ""),
                etype=str2error(json.get("type")),
            )
        del json["status"]
        del json["id"]
        return json

    async def handle_packet(self, message: str, extra: dict = None):
        return self._handle_json(*await self.connection.write_packet(message, extra))

    # =========================
    #   Mod Integration Helpers
    # =========================

    @classmethod
    def _generate_dump_mesa_config(cls, cmd: str):
        async def func(self):
            return await self.handle_packet(cmd)
        return func

    @classmethod
    def _generate_get_mesa_config_item(cls, cmd: str):
        async def func(self, category: str, name: str):
            return await self.handle_packet(cmd, {
                "category": category,
                "name": name,
            })
        return func

    @classmethod
    def _generate_set_mesa_config_item(cls, cmd: str):
        async def func(self, category: str, name: str, value):
            return await self.handle_packet(cmd, {
                "category": category,
                "name": name,
                "value": value,
            })
        return func

    @classmethod
    def _generate_exec_mesa_config_item(cls, cmd: str):
        async def func(self, category: str, name: str, action: str = None):
            assert action is None or action in ("press", "release"), ValueError("Invalid action. Must be press or release")
            return await self.handle_packet(cmd, {
                **{
                    "category": category,
                    "name": name
                },
                **(
                    {} if action is None else {"action": action}
                )
            })
        return func

    # =========================
    #   Client/Player Info
    # =========================

    async def get_client_info(self):
        return await self.handle_packet("get client info")

    async def get_player_info(self):
        return await self.handle_packet("get player info")

    async def get_installed_mods(self):
        return (await self.handle_packet("get mod list")).get("mods")

    async def get_source_info(self):
        return await self.handle_packet("sources")
    # =========================
    #   Callback Management
    # =========================

    async def get_callback_states(self) -> dict[CallbackType, bool]:
        result = await self.handle_packet("get callbacks")
        return {
            string_callback_dict.get(k): v
            for k, v in result["callbacks"].items()
        }

    async def set_callbacks(self, callbacks: dict[CallbackType, bool]):
        payload = {k.value: v for k, v in callbacks.items()}
        return await self.handle_packet("set callbacks", {"callbacks": payload})

    async def clear_callbacks(self):
        return await self.handle_packet("clear callbacks")

    # =========================
    #   World/Block/Chunk Access
    # =========================

    async def get_block(self, x: int, y: int, z: int) -> dict:
        pt, data = await self.connection.write_packet("get block", {"x": x, "y": y, "z": z})
        if pt == ord('j'):
            return self._handle_json(pt, data)
        return data.unpack()

    async def list_loaded_chunk_segments(self) -> list:
        return (await self.handle_packet("list loaded chunks")).get("chunks")

    async def get_chunk(self, cx: int, cz: int) -> Chunk | dict:
        pt, data = await self.connection.write_packet("get chunk", {"cx": cx, "cz": cz})
        if pt == ord('j'):
            return self._handle_json(pt, data)
        return Chunk.from_network(BytesIO(data))

    # =========================
    #   World/Server Management
    # =========================

    async def get_server_list(self):
        return await self.handle_packet("get server list")

    async def get_world_list(self):
        return await self.handle_packet("get worlds")

    async def join_world(self, name: str):
        return await self.handle_packet("join world", {"load world": name})

    async def join_server(self, address: str):
        return await self.handle_packet("join server", {"address": address})

    # =========================
    #   Player State Queries
    # =========================

    async def get_freecam_state(self) -> bool:
        return (await self.handle_packet("is freecam"))["is freecam"]

    async def get_freerot_state(self) -> bool:
        return (await self.handle_packet("is freerot"))["is freerot"]

    async def get_no_walk_state(self) -> bool:
        return (await self.handle_packet("is nowalk"))["is nowalk"]

    async def get_headless_state(self) -> bool:
        return (await self.handle_packet("is headless"))["is headless"]

    # =========================
    #   Player State Setters
    # =========================

    async def set_freecam(self, enabled: bool = True):
        return await self.handle_packet("set freecam", {"enabled": enabled})

    async def set_freerot(self, enabled: bool = True):
        return await self.handle_packet("set freerot", {"enabled": enabled})

    async def set_no_walk(self, enabled: bool = True):
        return await self.handle_packet("set nowalk", {"enabled": enabled})

    async def set_headless(self, enabled: bool = True):
        return await self.handle_packet("set headless", {"enabled": enabled})

    # =========================
    #   Baritone/Automation
    # =========================

    async def baritone_goto(self, x: int, y: int, z: int):
        return await self.handle_packet(
            "baritone goto", {"x": x, "y": y, "z": z}
        )

    # =========================
    #   Chat/Command Messaging
    # =========================

    async def send_chat_message(self, message: str):
        return await self.handle_packet(
            "send chat message", {"message": message}
        )

    async def send_execute_command(self, message: str):
        return await self.handle_packet(
            "execute command", {"message": message}
        )

    async def display_message(self, message: str):
        return await self.handle_packet(
            "display chat message", {"message": message}
        )

    async def overview_message(self, message: str):
        return await self.handle_packet(
            "overview message", {"message": message}
        )

    # =========================
    #   Input/Control
    # =========================

    async def clear_inputs(self):
        return await self.handle_packet("clear force input")

    async def get_forced_inputs(self):
        return (await self.handle_packet("get forced input")).get("inputs")

    async def force_inputs(self, inputs: list[tuple[InputButton, bool]]):
        return await self.handle_packet(
            "force inputs",
            {
                "inputs": {
                    k[0].value: k[1] for k in inputs
                }
            },
        )

    async def remove_forced_inputs(self, inputs: list[InputButton]):
        return await self.handle_packet(
            "force inputs",
            {
                "remove": [k.value for k in inputs]
            },
        )

    # =========================
    #   Player Movement/Rotation
    # =========================

    async def arotate(
        self,
        pitch: float,
        yaw: float,
        speed: float = 3,
        method: RoMethod = RoMethod.SINE_IN_OUT,
    ):
        return await self.handle_packet(
            "algorithmic rotation",
            {
                "pitch": pitch,
                "yaw": yaw,
                "degrees per tick": speed,
                "interpolation": method.value,
            },
        )

    async def irotate(self, pitch: float, yaw: float):
        return await self.handle_packet(
            "instantaneous rotation",
            {
                "pitch": pitch,
                "yaw": yaw,
            },
        )

    async def set_hotbar_slot(self, slot: int):
        assert 1 <= slot <= 9, "Invalid slot value"
        return await self.handle_packet("set hotbar slot", {"slot": slot})

    async def attack(self):
        return await self.handle_packet("attack key click")

    async def use(self):
        return await self.handle_packet("use key click")

    async def set_directional_walk(
        self, degrees: float, speed: float = 1, force=False
    ):
        return await self.handle_packet(
            "set directional movement degree",
            {
                "direction": degrees,
                "speed": speed,
                "force": force,
            },
        )

    async def set_directional_walk_vector(
        self, x: float, z: float, speed=1, force=False
    ):
        return await self.handle_packet(
            "set directional movement vector",
            {
                "x": x,
                "z": z,
                "speed": speed,
                "force": force,
            },
        )

    async def stop_directional_walk(self):
        return await self.handle_packet("clear directional movement")

# Generate functions for all the mod integrations
for (dump_cmd, get_cmd, set_cmd, exec_cmd) in _MOD_INTEGRATIONS:
    setattr(Player, dump_cmd.replace(" ", "_"), Player._generate_dump_mesa_config(dump_cmd))
    setattr(Player, get_cmd.replace(" ", "_"), Player._generate_get_mesa_config_item(get_cmd))
    setattr(Player, set_cmd.replace(" ", "_"), Player._generate_set_mesa_config_item(set_cmd))
    setattr(Player, exec_cmd.replace(" ", "_"), Player._generate_exec_mesa_config_item(exec_cmd))