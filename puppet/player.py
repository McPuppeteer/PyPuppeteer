from io import BytesIO

from .connection import *
from .world import Chunk

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
        """
        Discover and connect to a player by broadcast.
        """
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
        """
        Handles JSON packets received from the server.

        :param packet_type: The type of the packet (should be 'j').
        :param json: The JSON data received.
        :return: The processed JSON data.
        :raises PuppeteerError: If the JSON contains an error status.
        """
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
        """
        Write a json packet, send it, and raise any errors.
        :raises PuppeteerError: If the JSON contains an error status.
        """
        return self._handle_json(*await self.connection.write_packet(message, extra))

    # =========================
    #   Mod Integration Helpers
    # =========================

    @classmethod
    def _generate_dump_mesa_config(cls, cmd: str):
        async def func(self):
            """ Returns the config json associated with this mod. """
            return await self.handle_packet(cmd)
        return func

    @classmethod
    def _generate_get_mesa_config_item(cls, cmd: str):
        async def func(self, category: str, name: str):
            """ Returns the config json value of the config item associated with this mod. """
            return await self.handle_packet(cmd, {
                "category": category,
                "name": name,
            })
        return func

    @classmethod
    def _generate_set_mesa_config_item(cls, cmd: str):
        async def func(self, category: str, name: str, value):
            """ Sets the config value for a given mod config item. """
            return await self.handle_packet(cmd, {
                "category": category,
                "name": name,
                "value": value,
            })
        return func

    @classmethod
    def _generate_exec_mesa_config_item(cls, cmd: str):
        async def func(self, category: str, name: str, action: str = None):
            """ Executes a given hotkey associated with this mod. """
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
        """ Returns a dictionary of a bunch of information about the game client """
        return await self.handle_packet("get client info")

    async def get_player_info(self):
        """ Returns a dictionary of a bunch of information about the player, you MUST be in game to do this. """
        return await self.handle_packet("get player info")

    async def get_installed_mods(self):
        """ Returns a list of installed mods. """
        return (await self.handle_packet("get mod list")).get("mods")

    async def get_sources(self):
        """
        This will give you a bunch of information about the mod version,
        including the git commit hash, a link to where the source code
        for that build can be found, and the AGPL license.

        This is included to abide by the AGPL, which requires
        any user of the program, even across the network, to have
        the ability to have the source code.

        Note: If you are forking the mod, please modify: `fabric.mod.json`
              to include your github repo.
        """
        return await self.handle_packet("sources")
    async def _list_commands(self):
        """ Returns a list of available commands. Note: Also included in ```get_client_info()``` """
        return await self.handle_packet("list commands")

    async def has_baritone(self):
        """ Returns true if baritone is installed. """

        # Typically "test baritone" returns an error, but this way
        # we don't have to bother the exception system
        _, jso = await self.connection.write_packet("test baritone")
        return jso["status"] == "ok"

    # =========================
    #   Callback Management
    # =========================

    async def get_callback_states(self) -> dict[CallbackType, bool]:
        """
        Tells you what callbacks are currently enabled in the client. Use ``set_callbacks()`` to enable them.

        :return: A dictionary of the callback states.
        """
        result = await self.handle_packet("get callbacks")
        return {
            string_callback_dict.get(k): v
            for k, v in result["callbacks"].items()
        }

    async def set_callbacks(self, callbacks: dict[CallbackType, bool]):
        """
        Enable more callbacks being sent to the player.

        :param callbacks: A dictionary (identical to the return of ``get_callback_states()``) of what callbacks you want to enable.
        """
        payload = {k.value: v for k, v in callbacks.items()}
        return await self.handle_packet("set callbacks", {"callbacks": payload})

    async def clear_callbacks(self):
        """ Clear all callbacks being sent to the player.  """
        return await self.handle_packet("clear callbacks")

    # =========================
    #   World/Block/Chunk Access
    # =========================

    async def get_block(self, x: int, y: int, z: int) -> dict:
        """
        Asks for a specific block somewhere in the world

        :param x: The x coordinate of the block to ask.
        :param y: The y coordinate of the block to ask.
        :param z: The z coordinate of the block to ask.
        :return: A dictionary of the block data.
        """
        pt, data = await self.connection.write_packet("get block", {"x": x, "y": y, "z": z})
        if pt == ord('j'):
            return self._handle_json(pt, data)
        return data.unpack()

    async def list_loaded_chunk_segments(self) -> list:
        """ Returns a list of loaded chunk segments. """
        return (await self.handle_packet("list loaded chunks")).get("chunks")

    async def get_chunk(self, cx: int, cz: int) -> Chunk | dict:
        """
        Asks for a specific chunk somewhere in the world.
        :param cx: Location of the chunk, note this is 16x smaller than the normal coordinates
        :param cz: Location of the chunk, note this is 16x smaller than the normal coordinates

        :return: On success, a Chunk object, or raises an error
        """
        pt, data = await self.connection.write_packet("get chunk", {"cx": cx, "cz": cz})
        if pt == ord('j'):
            return self._handle_json(pt, data)
        return Chunk.from_network(BytesIO(data))

    # =========================
    #   World/Server Management
    # =========================

    async def get_server_list(self):
        """ Gets all the multiplayer servers in your server list, along with the "hidden" ones (your direct connect history). """
        return await self.handle_packet("get server list")

    async def get_world_list(self):
        """
        List ALL the worlds on this minecraft instances .minecraft folder.

        This can be slow on some installs, as some users may have **thousands** of worlds.
        """
        return await self.handle_packet("get worlds")

    async def join_world(self, name: str):
        """
        Joins a local world. The name **needs** to be from the 'load name' from getWorldList()

        :param name: The name of the world to join, **needs** to match the 'load name' from ``getWorldList()``
        """
        return await self.handle_packet("join world", {"load world": name})

    async def join_server(self, address: str):
        """
        Joins a multiplayer server

        :param address: Server ip to connect to
        """
        return await self.handle_packet("join server", {"address": address})

    # =========================
    #   Player State Queries
    # =========================

    async def get_freecam_state(self) -> bool:
        """ Tells you if freecam is currently enabled. """
        return (await self.handle_packet("is freecam"))["is freecam"]

    async def get_freerot_state(self) -> bool:
        """ Tells you if freeroot is currently enabled. """
        return (await self.handle_packet("is freerot"))["is freerot"]

    async def get_no_walk_state(self) -> bool:
        """ Tells you if no walk is currently enabled. """
        return (await self.handle_packet("is nowalk"))["is nowalk"]

    async def get_headless_state(self) -> bool:
        """ Tells your if the client is currently headless. """
        return (await self.handle_packet("is headless"))["is headless"]

    # =========================
    #   Player State Setters
    # =========================

    async def set_freecam(self, enabled: bool = True):
        """ Set if freecam is currently enabled. """
        return await self.handle_packet("set freecam", {"enabled": enabled})

    async def set_freerot(self, enabled: bool = True):
        """ Set if freeroot is currently enabled. """
        return await self.handle_packet("set freerot", {"enabled": enabled})

    async def set_no_walk(self, enabled: bool = True):
        """ Set if no walk is currently enabled. """
        return await self.handle_packet("set nowalk", {"enabled": enabled})

    async def set_headless(self, enabled: bool = True):
        """
        Put the client into a "headless" state. This means you will no longer
        see the window on your screen. It theoretically should take less
        resources to run, as the rendering system is disabled, however,
        at least on my system, the effect is minimal.

        This is a **dangerous** mode! If, for whatever reason, your Puppeteer
        server crashes, will have **no method to recover**. And will be left
        with nothing but the task manager to save you!

        **Use with caution!**
        """
        return await self.handle_packet("set headless", {"enabled": enabled})

    # =========================
    #   Baritone/Automation
    # =========================

    async def baritone_goto(self, x: int, y: int, z: int):
        """
        Tells baritone to go to a specific location.

        :param x: The x coordinate
        :param y: The y coordinate
        :param z: The z coordinate
        """
        return await self.handle_packet(
            "baritone goto", {"x": x, "y": y, "z": z}
        )

    # =========================
    #   Chat/Command Messaging
    # =========================

    async def send_chat_message(self, message: str):
        """
        Sends a public chat message. If prepended with "/", will execute a command.

        :param message: The message to send.
        """
        return await self.handle_packet(
            "send chat message", {"message": message}
        )

    async def send_execute_command(self, message: str):
        """
        Runs a command.

        :param message: The command to execute

        Note: Do **NOT** include the "/"

        Ex: ``gamemode creative`` to set the gamemode to creative.
        """
        return await self.handle_packet(
            "execute command", {"message": message}
        )

    async def display_message(self, message: str):
        """
        Displays a message in chat. This is private
        :param message:  Message to display in chat
        """
        return await self.handle_packet(
            "display chat message", {"message": message}
        )

    async def overview_message(self, message: str):
        """
        Shows a message above the users hotbar, this is great for informational status updates.

        For example, telling the user when something is starting and ending.

        :param message: Message to display above the hotbar
        """
        return await self.handle_packet(
            "overview message", {"message": message}
        )

    # =========================
    #   Input/Control
    # =========================

    async def clear_inputs(self):
        """ Remove all forced button presses. """
        return await self.handle_packet("clear force input")

    async def get_forced_inputs(self):
        """
        Reports the state of if certain input methods are forced. A key not being present
        indicates that no input is being forced. If a key is set to false, it is being forced up.
        And if a key is set to true, it is forced down.
        """
        return (await self.handle_packet("get forced input")).get("inputs")

    async def force_inputs(self, inputs: list[tuple[InputButton, bool]]):
        """
        Force down/up buttons. If a button is not mentioned, it will not be impacted. Meaning that if it is already pressed,
        it will still be pressed if you do not update its state.

        :param inputs: List of tuples of (InputButton, bool). Where the bool is the **forced state** of the input. Meaning
                       setting to False indicates the **user cannot press** that key.
        """
        return await self.handle_packet(
            "force inputs",
            {
                "inputs": {
                    k[0].value: k[1] for k in inputs
                }
            },
        )

    async def remove_forced_inputs(self, inputs: list[InputButton]):
        """
        Disables the forced state of inputs. If a button is not mentioned, it will not be impacted.
        A complete list of inputs will result in identical behavior to ``clear_inputs()``

        :param inputs: A list if inputs, each input will have is state no longer controlled.
        """
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
        """
        Smoothly, and realistically, rotate the player.

        :param pitch: Pitch angle in degrees.
        :param yaw: Yaw angle in degrees.
        :param speed: Speed of rotation. This can be generally interpreted as `degrees per tick`, but with certain rotation methods
                      this will not be true.
        :param method: What interpolation method is used. This will not change the time required to rotate, but instead how it looks.
        """
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
        """
        Instantly set the player's rotation. This looks like you are cheating.

        :param pitch: Pitch angle in degrees.
        :param yaw: Yaw angle in degrees.
        """
        return await self.handle_packet(
            "instantaneous rotation",
            {
                "pitch": pitch,
                "yaw": yaw,
            },
        )

    async def set_hotbar_slot(self, slot: int):
        """
        Set the current hotbar slot.

        :param slot: [1, 9] are valid hotbar slots
        """
        assert 1 <= slot <= 9, "Invalid slot value"
        return await self.handle_packet("set hotbar slot", {"slot": slot})

    async def attack(self):
        """ Tells the player to punch. Single left click """
        return await self.handle_packet("attack key click")

    async def use(self):
        """ Tells the player to use an item/block. Single right click """
        return await self.handle_packet("use key click")

    async def set_directional_walk(
        self, degrees: float, speed: float = 1, force=False
    ):
        """
        Force the player to walk in a certain direction. Directional walking allows you to make the player walk towards a block.
        The direction the player is walking in is absolute, meaning the user can look around without interfacing.

        :param degrees: The **global** direction, in degrees, from 0-360, of where the user will walk.
        :param speed: Should be from 0-1. With zero being no movement, and one being regular walk speed.
        :param force: If false, will clamp the speed. If true, will allow any speed value, basically being speed hacks.
        """
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
        """
        Force the player to walk in a certain direction. Directional walking allows you to make the player walk towards a block.
        The direction the player is walking in is absolute, meaning the user can look around without interfacing.

        The difference between this and ``set_directional_walk()`` is that you input a global vector. For example,
        to walk in the `+x` direction, use parameters x=1, z=0. To walk equally in the `+x` and `+z` direction, use
        parameters x=1, z=1. Negative directions **are** supported. Vectors **are normalized**. so feel free to use
        large values.

        :param x: The x component of the direction.
        :param z: The z component of the direction.
        :param speed: Should be from 0-1. With zero being no movement, and one being regular walk speed.
        :param force: If false, will clamp the speed. If true, will allow any speed value, basically being speed hacks.
        """
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
        """No longer be directional walking"""
        return await self.handle_packet("clear directional movement")

# Generate functions for all the mod integrations
for (dump_cmd, get_cmd, set_cmd, exec_cmd) in _MOD_INTEGRATIONS:
    setattr(Player, dump_cmd.replace(" ", "_"), Player._generate_dump_mesa_config(dump_cmd))
    setattr(Player, get_cmd.replace(" ", "_"), Player._generate_get_mesa_config_item(get_cmd))
    setattr(Player, set_cmd.replace(" ", "_"), Player._generate_set_mesa_config_item(set_cmd))
    setattr(Player, exec_cmd.replace(" ", "_"), Player._generate_exec_mesa_config_item(exec_cmd))