from io import BytesIO
from typing import *

from .connection import *
from .world import Chunk

_MOD_INTEGRATIONS = (
    ("dump itemscroller config", "get itemscroller config item", "set itemscroller config item",
     "exec itemscroller config item"),
    ("dump litematica config", "get litematica config item", "set litematica config item",
     "exec litematica config item"),
    ("dump tweakeroo config", "get tweakeroo config item", "set tweakeroo config item", "exec tweakeroo config item"),
    ("dump malilib config", "get malilib config item", "set malilib config item", "exec malilib config item"),
    ("dump minihud config", "get minihud config item", "set minihud config item", "exec minihud config item"),
)


class Player:
    """
    Main wrapper class around the connection. It is recommended to
    create a new instance using the ```discover()``` function, in
    addition to using a context manager.

    Ex:
    ```
    async with Player.discover() as p:
        print(await p.attack())
    ```
    """

    _callbacks: Dict[str, Callable[[Dict[Any, Any]], None]]

    # =========================
    #   Connection Management
    # =========================

    async def _callback_handler(self, info):
        print(info)

    def __init__(self, connection: ClientConnection):
        self.connection = connection
        self.connection.callback_handler = self._callback_handler

        self._callbacks = {}

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

    def _handle_json(self, packet_type: int, json: Dict) -> Dict:
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

    async def handle_packet(self, message: str, extra: Dict = None):
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
            assert action is None or action in ("press", "release"), ValueError(
                "Invalid action. Must be press or release")
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

    async def get_callback_states(self) -> Dict[CallbackType, bool]:
        """
        Tells you what callbacks are currently enabled in the client. Use ``set_callbacks()`` to enable them.

        :return: A dictionary of the callback states.
        """
        result = await self.handle_packet("get callbacks")
        return {
            string_callback_dict.get(k): v
            for k, v in result["callbacks"].items()
        }

    async def set_callbacks(self, callbacks: Dict[CallbackType, bool]):
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

    async def get_block(self, x: int, y: int, z: int) -> Dict:
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

    async def list_loaded_chunk_segments(self) -> List:
        """ Returns a list of loaded chunk segments. """
        return (await self.handle_packet("list loaded chunks")).get("chunks")

    async def get_player_inventory_contents(self):
        """ Returns JSON data of the player's inventory. Throws an error if a container is open"""
        return await self.handle_packet("get player inventory")

    async def get_player_inventory(self) -> "PlayerInventory":
        """ Returns an object of the player's inventory. Throws an error if a container is open"""

        inventory = await self.get_player_inventory_contents()
        return PlayerInventory(self, inventory["slots"], inventory["name"])

    async def get_open_inventory_contents(self):
        return await self.handle_packet("get open inventory")

    async def click_container_button(self, button : int):
        return await self.handle_packet("click inventory button", {"button": button})

    async def get_merchant_trades(self):
        return await self.handle_packet("get trades")

    async def select_trade(self, index : int):
        return await self.handle_packet("select trade", {"index": index})

    async def set_anvil_name(self, name : str):
        return await self.handle_packet("set anvil name", {"name": name})

    async def set_beacon_effect(self, primary : str | None, secondary : str | None = None):
        return await self.handle_packet("set beacon effect", {
            **({} if primary is None else  {"primary": primary}),
            **({} if secondary is None else {"secondary": secondary})
        })
    async def get_enchantments(self):
        return await self.handle_packet("get enchantments")
    async def get_chunk(self, cx: int, cz: int) -> Chunk:
        """
        Asks for a specific chunk somewhere in the world.
        :param cx: Location of the chunk, note this is 16x smaller than the normal coordinates
        :param cz: Location of the chunk, note this is 16x smaller than the normal coordinates

        :return: On success, a Chunk object, or raises an error
        """
        pt, data = await self.connection.write_packet("get chunk", {"cx": cx, "cz": cz})
        if pt == ord('j'):
            self._handle_json(pt, data)
            assert False, "Unreachable"
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

    async def force_inputs(self, inputs: List[Tuple[InputButton, bool]]):
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

    async def remove_forced_inputs(self, inputs: List[InputButton]):
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
            self, degrees: float, speed: float = 1, force: bool = False
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
            self, x: float, z: float, speed: float = 1, force: bool = False
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


class Inventory:
    # Constant
    container_type: str = None

    # Set on instance
    screen_name: str | None
    player: Player
    slot_data: List[Dict]

    # Starting slot of player inventory, None
    # if player inventory is disabled
    player_inventory_offset: int = 9

    container_offset: int = None
    container_width: int = None
    container_height: int = None

    def __init__(self, player: Player, slot_data, screen_name: str | None = None, horse_data : Dict | None = None):
        self.player = player
        self.screen_name = screen_name

        self.slot_data = [{"id": i, **slot} for i, slot in enumerate(slot_data)]
        assert self.container_type is not None, "Cannot initialize absract inventory"

    def get_slot(self, slot: int) -> Dict:
        """ Gets a slot by its id """
        return self.slot_data[slot]

    def get_inventory_slot(self, row: int, column: int):
        """
        Gets a slot WITHIN THE PLAYER'S INVENTORY. This will work
        regardless of what inventory is open, with the exception of the lecture,
        and other inventories that lack the player's inventory.

        :param row: A row, starting at 0, counting up FROM the TOP of the screen. (0 is the top)
        :param column: A column, starting at 0, counting up LEFT to right of the screen. (0 is the left)
        """
        assert self.player_inventory_offset is not None, "This inventory lacks the player's inventory"

        return self.get_slot(row * 9 + column + self.player_inventory_offset)

    def get_container_slot(self, row: int, column: int):
        """
        Gets a slot WITHIN THE CONTAINER'S INVENTORY. This will ONLY work
        if the container has a row/col based inventory.

        :param row: A row, starting at 0, counting up FROM the TOP of the screen. (0 is the top)
        :param column: A column, starting at 0, counting up LEFT to right of the screen. (0 is the left)
        """
        assert self.container_offset is not None, "This inventory lacks the container's inventory"

        return self.get_slot(
            row * self.container_width + column
            + self.container_offset
        )


class PlayerInventory(Inventory):
    player_inventory_offset = 9
    container_type = "inventory"

    container_offset = 1
    container_width = 2
    container_height = 2

    def get_offhand(self):
        return self.get_slot(45)

    def get_crafting_slot(self, offset):
        return self.get_slot(1 + offset)

    def get_crafting_output(self):
        return self.get_slot(0)

    def get_helmet(self):
        return self.get_slot(5)

    def get_chestplate(self):
        return self.get_slot(6)

    def get_legging(self):
        return self.get_slot(7)

    def get_boots(self):
        return self.get_slot(8)

class Generic9x1(Inventory):
    container_type = "generic_9x1"
    player_inventory_offset = 9

    container_offset = 0
    container_width = 9
    container_height = 1

class Generic9x2(Inventory):
    container_type = "generic_9x2"
    player_inventory_offset = 18

    container_offset = 0
    container_width = 9
    container_height = 2

class Generic9x3(Inventory):
    container_type = "generic_9x3"
    player_inventory_offset = 27

    container_offset = 0
    container_width = 9
    container_height = 3

class Generic9x4(Inventory):
    container_type = "generic_9x4"
    player_inventory_offset = 36

    container_offset = 0
    container_width = 9
    container_height = 4

class Generic9x5(Inventory):
    container_type = "generic_9x5"
    player_inventory_offset = 45

    container_offset = 0
    container_width = 9
    container_height = 5

class Generic9x6(Inventory):
    container_type = "generic_9x6"
    player_inventory_offset = 54

    container_offset = 0
    container_width = 9
    container_height = 6

class Generic3x3(Inventory):
    container_type = "generic_3x3"
    player_inventory_offset = 9

    container_offset = 0
    container_width = 3
    container_height = 3

class Crafter(Generic3x3):
    container_type = "crafter"

    # TODO: Buttons

    def get_crafting_output(self):
        return self.get_slot(45)
class ShulkerBox(Generic9x3):
    container_type = "shulker_box"


class Generic2Input(Inventory):
    player_inventory_offset = 3

    def get_input1(self):
        return self.get_slot(0)
    def get_input2(self):
        return self.get_slot(1)
    def get_output(self):
        return self.get_slot(2)

class Anvil(Generic2Input):
    container_type = "anvil"

    async def set_name(self, name : str):
        return await self.player.set_anvil_name(name)

class Grindstone(Generic2Input):
    container_type = "grindstone"

class Merchant(Generic2Input):
    container_type = "merchant"

    async def get_trades(self):
        return await self.player.get_merchant_trades()
    async def select_trade(self, index : int):
        return await self.player.select_trade(index)

class CartographyTable(Generic2Input):
    container_type = "cartography_table"

class Beacon(Inventory):
    container_type = "beacon"
    player_inventory_offset = 1

    def get_payment_slot(self):
        return self.get_slot(0)
    async def set_effects(self, primary : None | str = None, secondary : None | str = None):
        return self.player.set_beacon_effect(primary, secondary)

class Furnace(Inventory):
    container_type = "furnace"
    player_inventory_offset = 3

    def get_furnace_output(self):
        return self.get_slot(2)
    def get_furnace_fuel(self):
        return self.get_slot(1)
    def get_furnace_ingredient(self):
        return self.get_slot(0)
class BlastFurnace(Furnace):
    container_type = "blast_furnace"
class Smoker(Furnace):
    container_type = "smoker"
class BrewingStand(Inventory):
    container_type = "brewing_stand"
    player_inventory_offset = 5

    def get_blaze_powder(self):
        return self.get_slot(4)

    def get_potion_ingredient(self):
        return self.get_slot(3)
    def get_potion_output(self, index = 0):
        assert index <= 2
        # No offset
        return self.get_slot(index)
class CraftingTable(Generic3x3):
    container_type = "crafting_table"
    container_offset = 1
    player_inventory_offset = 10

    def get_crafting_output(self):
        return self.get_slot(0)
class EnchantmentTable(Inventory):
    container_type = "enchantment"
    player_inventory_offset = 2

    def get_item(self):
        return self.get_slot(0)
    def get_lapis(self):
        return self.get_slot(1)

    async def get_enchants(self):
        return await self.player.get_enchantments()
    async def select_enchantment(self, index : int):
        assert 0 <= index <= 2

        return await self.player.click_container_button(index)


class Hopper(Inventory):
    container_type = "hopper"
    player_inventory_offset = 5

    container_offset = 0
    container_width = 5
    container_height = 1

class Lectern(Inventory):
    container_type = "lectern"
    player_inventory_offset = None
    # TODO: Buttons
class Loom(Inventory):
    container_type = "loom"
    player_inventory_offset = 4
    def get_banner(self):
        return self.get_slot(0)
    def get_dye(self):
        return self.get_slot(1)
    def get_pattern(self):
        return self.get_slot(2)
    def get_output(self):
        return self.get_slot(3)

class SmithingTable(Inventory):
    container_type = "smithing"
    player_inventory_offset = 4

    def get_template(self):
        return self.get_slot(0)
    def get_base_item(self):
        return self.get_slot(1)
    def get_additional_item(self):
        return self.get_slot(2)
    def get_output(self):
        return self.get_slot(3)
class StoneCutter(Inventory):
    container_type = "stonecutter"
    player_inventory_offset = 2
    # TODO: Buttons

    def get_input(self):
        return self.get_slot(0)
    def get_output(self):
        return self.get_slot(1)

# Includes: Horse, Donkey, Mule, Llama, Camel, etc
#   All these animals share a saddle slot, and an amor slot (these can be hidden)
#   along with an inventory which is somethimes there 
class EntityWithInventory(Inventory):
    # Feels like such a Microsoft thing to do, keep
    # adding new stuff and wedge it under an old system
    container_type = "horse"

    def __init__(self, player: Player, slot_data, screen_name: str | None = None, horse_data = None):
        assert horse_data is not None

        self.container_height = 3
        self.container_width = horse_data["inventory cols"]

        self.player_inventory_offset = 2 + 3 * self.container_height

        super().__init__(player, slot_data, screen_name, horse_data=horse_data)
    def get_saddle(self):
        return self.get_slot(0)
    def get_armor(self):
        return self.get_slot(1)
