import asyncio
from io import BytesIO
from json.encoder import py_encode_basestring
from types import coroutine
from typing import *
from collections.abc import Iterable


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
CALLBACK_TYPE = Callable[[Dict[Any, Any]], Coroutine[Any, Any, None] | None] | None
def _handle_json(packet_type: int, json: Dict) -> Dict:
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


T = TypeVar("T")
R = TypeVar("R")
class LazyRequest(Generic[T], Awaitable[T]):
    """
    A special awaitable object. Typically you can use this like
    a regular couroutine (i.e. you await it). However it also can
    be passed along to other functions to bundle packets together

    
    """

    _connection : ClientConnection
    _message : str
    _extra : Dict | None
    _raw : bool
    _required_type : int
    _modifier : Callable[[dict], T] | None
    

    _executed : bool
    def __init__(self, connection : ClientConnection, message: str, extra: Dict | None = None, raw : bool = False, required_type : int = ord('j'), modifier : Callable[[dict], T] | None = None):
        """
        :param connection: The client connection to use when its time to send the packet
        :param message: Command string to specify what command is being used  
        :param extra: Extra JSON data to be sent along
        :param raw: Set to true for json error handling, false for binary or NBT
        :param required_type: Should be ord('n'), ord('j'), or ord('b')
        :param modifier: A predicate of how to process the packet. When null the raw packet
                         contents are returned. Packet contents are determined by the packet
                         return type.
        """
        self._connection = connection
        self._message = message
        self._extra = extra
        self._raw = raw
        self._modifier = modifier
        self._required_type = required_type

        self._executed = False
    
    def _transform_future(self, fut : Awaitable[Any]) -> Awaitable[T]:
        async def tmp():
            packet_type, data = await fut

            if packet_type == ord('j') and data.get("status") == "error":
                raise PuppeteerError(
                    "Error: " + data.get("message", ""),
                    etype=str2error(data.get("type"))
                )

            if packet_type != self._required_type:
                raise PuppeteerError("Packet type was not as expeced")
            if not self._raw:
                data = _handle_json(packet_type, data)
            if self._modifier is not None:
                data = self._modifier(data)


            return cast(T, data)
        return tmp()

    def map(self, predicate : Callable[[T], R]) -> "LazyRequest[R]":
        """
        Stack a new modifier ontop of an current modifiers. This
        creates a new PacketFormat instance.

        :param predicate: Take the old return value, and transform it.
        """
        assert not self._executed
        oldModifier = self._modifier
        def tmp(data):
            if oldModifier is not None:
                data = oldModifier(data)
            return predicate(data)
        return cast(LazyRequest[R], LazyRequest(
            self._connection, self._message, extra=self._extra, raw=self._raw, required_type=self._required_type, modifier=tmp))



        
    def soft_send(self) -> tuple[dict, Awaitable[T]]:
        """
        Generates the packet as it would be if sent to the network.
        This is used for bundled packets.
        """
        packet, fut =  self._connection._write_packet_internal(self._message, self._extra)
        return packet, cast(Awaitable[T], self._transform_future(fut))

    async def start(self) -> T:
        """ Convert into a regualar coroutine """
        return await self 



    def __await__(self):
        assert not self._executed, AttributeError("This Packet has already been sent")

        self._executed = True

        fut = self._transform_future(self._connection.write_packet(self._message, self._extra))
        return fut.__await__()







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

    _callbacks: Dict[str, CALLBACK_TYPE]

    def panic(self):
        return LazyRequest(self.connection, "panic")

    # =========================
    #   Connection Management
    # =========================
    default_callback : CALLBACK_TYPE

    async def _callback_handler(self, info):
        callback = self._callbacks.get(info["type"])
        callback = callback if callback is not None else self.default_callback
        if callback is None:
            return
        res = callback(info)
        if asyncio.iscoroutine(res):
            asyncio.create_task(res)
    def __init__(self, connection: ClientConnection):
        self.connection = connection
        self.connection.callback_handler = self._callback_handler

        self._callbacks = {}
        self.default_callback = None

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


    async def wait_for_chat(self, predicate: Callable[[str], bool] | str) -> str:
        """
        Wait until a specific pattern in a chat message is received.

        :param predicate: A function OR a string. If a string type is received, checks
                          if the string appears EXACTLY. If a function is received, acts
                          as a predicate. The function is assumed to take a single string
                          as an argument, and return a boolean. Where a ``true`` value causes
                          the function to return.
        :return: The message that ends the wait
        """
        if type(predicate) is str:
            old = predicate
            predicate = lambda x: old in x

        while not predicate(ret := (await self.wait_for_callback(CallbackType.CHAT))["message"]):
            pass
        return ret
    # =========================
    #   Mod Integration Helpers
    # =========================

    @classmethod
    def _generate_dump_mesa_config(cls, cmd: str) -> Callable[[], LazyRequest[dict]]:
        def func(self):
            """ Returns the config json associated with this mod. """
            return LazyRequest(self.connection, cmd)

        return cast(Callable[[], LazyRequest[dict]], func)

    @classmethod
    def _generate_get_mesa_config_item(cls, cmd: str) -> Callable[[], LazyRequest[dict]]:
        def func(self, category: str, name: str):
            """ Returns the config json value of the config item associated with this mod. """
            return LazyRequest(self.connection, cmd, {
                "category": category,
                "name": name,
            })

        return cast(Callable[[], LazyRequest[dict]], func)

    @classmethod
    def _generate_set_mesa_config_item(cls, cmd: str) -> Callable[[], LazyRequest[dict]]:
        def func(self, category: str, name: str, value):
            """ Sets the config value for a given mod config item. """
            return LazyRequest(self.connection, cmd, {
                "category": category,
                "name": name,
                "value": value,
            })

        return cast(Callable[[], LazyRequest[dict]], func)
    @classmethod
    def _generate_exec_mesa_config_item(cls, cmd: str):
        def func(self, category: str, name: str, action: str = None):
            """ Executes a given hotkey associated with this mod. """
            assert action is None or action in ("press", "release"), ValueError(
                "Invalid action. Must be press or release")

            return LazyRequest(self.connection, cmd, {
                **{
                    "category": category,
                    "name": name
                },
                **(
                    {} if action is None else {"action": action}
                )
            })

        return func

    def _ignored_request(self, request : Coroutine | LazyRequest):
        """
        Make sure this packet is likely sent, but we don't care about the return. 
        Or if the connection is cut don't worry about it. 

        TLDR: Try your best, but be alright with faliure
        """

        coroutine = request.start() if isinstance(request, LazyRequest) else request

        # Don't yell it me if something bad happens
        asyncio.create_task(coroutine).add_done_callback(lambda t: None)


    def _bundle_internal(self, packets : Iterable[LazyRequest[Any]], method : BundleMethod = BundleMethod.INSTANT, ticks : int | None = None) -> Tuple[LazyRequest[dict], Tuple[Awaitable[Any]]]:
        packets, futures = zip(* (p.soft_send() for p in packets) )

        if ticks is not None and method is not BundleMethod.TICKLY:
            raise AttributeError("You can only set an amount of ticks using the TICKLY bundle method!")

        return LazyRequest(self.connection, "bundle", 
                           {"packets": packets,
                            "method": method.value,
                            **({} if ticks is None else {"ticks": ticks}) 
                            }), futures
        
    def bundle_p(self, packets : Iterable[LazyRequest[Any]], method : BundleMethod = BundleMethod.INSTANT, ticks : int | None = None) -> LazyRequest[Tuple[Awaitable[Any]]]:
        packet, futures = self._bundle_internal(packets, method=method, ticks=ticks)
        return packet.map(lambda _: futures)


    def bundle(self, packets : Iterable[LazyRequest[Any]], method : BundleMethod = BundleMethod.INSTANT, ticks : int | None = None) -> Tuple[Awaitable[Any]]:
        packet, futures = self._bundle_internal(packets, method=method, ticks=ticks)
        self._ignored_request(packet)
        return futures
        

    def sleep(self, ticks : int) -> LazyRequest[dict]:
        """ Sleep for N ticks. NOTE: Will block tasks that are enqueued after this """
        return LazyRequest(self.connection, "sleep", {"interval": ticks})



    # =========================
    #   Client/Player Info
    # =========================

    def get_client_info(self) -> LazyRequest[dict]:
        """ Returns a dictionary of a bunch of information about the game client """
        return LazyRequest(self.connection, "get client info")

    def get_player_info(self) -> LazyRequest[dict]:
        """ Returns a dictionary of a bunch of information about the player, you MUST be in game to do this. """
        return LazyRequest(self.connection, "get player info")

    def get_installed_mods(self) -> LazyRequest[list[dict]]:
        """ Returns a list of installed mods. """
        return LazyRequest(self.connection, "get mod list", modifier=lambda dic: dic.get("mods"))

    def get_sources(self) -> LazyRequest[dict]:
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
        return LazyRequest(self.connection, "sources")

    def _list_commands(self) -> LazyRequest[dict]:
        """ Returns a list of available commands. Note: Also included in ```get_client_info()``` """
        return LazyRequest(self.connection, "list commands")

    async def has_baritone(self) -> bool:
        """ Returns true if baritone is installed. NOTE: Not a LazyRequest"""

        # Typically "test baritone" returns an error, but this way
        # we don't have to bother the exception system
        _, jso = await self.connection.write_packet("test baritone")
        return jso["status"] == "ok"

    def ping(self) -> LazyRequest[dict]:
        """
        Pings the server.
        """
        return LazyRequest(self.connection, "ping")

    # =========================
    #   Callback Management
    # =========================

    def _get_callback_states(self) -> LazyRequest[Dict[CallbackType, bool]]:
        """
        Tells you what callbacks are currently enabled in the client. Use ``_set_callbacks()`` to enable them.

        :return: A dictionary of the callback states.
        """
        return cast(LazyRequest[Dict[CallbackType, bool]],
                    LazyRequest(self.connection, "get callbacks", modifier=lambda result: {
            string_callback_dict.get(k): v
            for k, v in result["typical callbacks"].items()
        }))

    def _get_packet_callback_states(self) -> LazyRequest[Dict[str, PacketCallbackState]]:
        """
        Tells you what packet callbacks are enabled in the client. Use ``_set_packet_callbacks()`` to enable them.

        :return: A dictionary of the packet callback states.
        """
        return cast(LazyRequest[Dict[str, PacketCallbackState]],
                    LazyRequest(self.connection, "get callbacks", modifier=lambda result: {
                        k: string_packet_state_dict.get(v)
                        for k, v in result["packet callbacks"].items()
        }))


    def _set_callbacks(self, callbacks: Dict[CallbackType, bool]) -> LazyRequest[dict]:
        """
        Enable more callbacks being sent to the player.

        :param callbacks: A dictionary (identical to the return of ``_get_callback_states()``) of what callbacks you want to enable.
        """
        payload = {k.value: v for k, v in callbacks.items()}
        return LazyRequest(self.connection, "set callbacks", {"callbacks": payload})

    def _set_packet_callbacks(self, callbacks: Dict[str, PacketCallbackState]) -> LazyRequest[dict]:
        """
        Enable specific packet callbacks being sent to the player.
        You should use ``_get_packet_callback_states()`` for a canonical list of packets enabled
        for this version. An example packet callback id is: ``clientbound/minecraft:set_chunk_cache_center``

        You should also use the wiki as a reference: https://minecraft.wiki/w/Java_Edition_protocol/Packets

        Also see PacketCallbackState for additional information.

        :param callbacks: A dictionary (identical to the return of ``_get_packet_callback_states()``) of what callbacks you want to enable.
        """
        return LazyRequest(self.connection, "set callbacks", {
            "callbacks": {
                k: v.value
                for k, v in callbacks.items()
            }
        })

    def _clear_callbacks(self) -> LazyRequest[Any]:
        """ Clear all callbacks being sent to the player.  """
        return LazyRequest(self.connection, "clear callbacks")
    def clear_callbacks(self) -> LazyRequest[Any]:
        """ Clear all the callbacks. """
        self._callbacks = {}
        return self._clear_callbacks()

    def set_callback(self, type: CallbackType, callback :  CALLBACK_TYPE) -> LazyRequest[dict]:
        """
        Set a function that will be called when an event occurs for the client.

        :param type: What type of event will fire the callback.
        :param callback: The function you want to call on that event.
                         Can be a coroutine, or a regular function. Taking
                         the event json as a parameter.
        """

        self._callbacks[type.value] = callback
        return self._set_callbacks({
            type: True
        })

    def remove_callback(self, type : CallbackType) -> LazyRequest[dict]:
        """ Remove a previously set callback. """
        del self._callbacks[type.value]

        return self._set_callbacks({
            type: False
        })

    async def wait_for_callback(self, type : CallbackType) -> dict:
        """ Binds until the client has an event occur. And return that event"""

        old_state = (await self._get_callback_states()).get(type, False)

        fut = asyncio.get_event_loop().create_future()
        old_callback = self._callbacks.get(type.value)

        async def tmp(info):
            if not fut.done():
                fut.set_result(info)
            if old_callback is not None:
                await old_callback(info)
                self._callbacks[type.value] = old_callback
            else:
                del self._callbacks[type.value]

        self._callbacks[type.value] = tmp

        # Try to save some time. 
        asyncio.create_task(self._set_callbacks({
            type: True
        }).start())



        ret = await fut

        # We don't care about this much
        self._ignored_request(self._set_callbacks({
            type: old_state
        }))

        return ret




    def set_packet_callback(self, idd : str, callbackType : PacketCallbackState, callback :  CALLBACK_TYPE) -> LazyRequest[dict]:
        """
        Set a function that will be called when the client receives a packet (or sends one).
        See the documentation of PacketCallbackState for more information.

        :param idd: The `resource id` of the packet. See: https://minecraft.wiki/w/Java_Edition_protocol/Packets
                    For a list of all the minecraft protocol packets and their network definition.
        :param callbackType: See PacketCallbackState
        :param callback: The function you want to call on that event. Can be a coroutine, or a regular function.
        """
        assert callbackType != PacketCallbackState.DISABLED

        def removal_wrapper(*args, **kwargs):
            del self._callbacks[idd]
            return callback(*args, **kwargs)

        # `Next` style callback types only trigger once
        if callbackType in (PacketCallbackState.NETWORK_SERIALIZED_NEXT, PacketCallbackState.NOTIFY_NEXT, PacketCallbackState.OBJECT_SERIALIZED_NEXT):
            self._callbacks[idd] = removal_wrapper
        else:
            self._callbacks[idd] = callback

        return self._set_packet_callbacks({idd: callbackType})

    def remove_packet_callback(self, idd : str) -> LazyRequest[dict]:
        """
        Remove a single packet callback.

        :param idd: The `resource id` of the packet whose callback you wish to no longer see.
        """
        del self._callbacks[idd]
        return self._set_packet_callbacks({
            idd: PacketCallbackState.DISABLED
        })




    # =========================
    #   World/Block/Chunk Access
    # =========================

    def get_block(self, x: int, y: int, z: int) -> LazyRequest[Dict]:
        """
        Asks for a specific block somewhere in the world

        :param x: The x coordinate of the block to ask.
        :param y: The y coordinate of the block to ask.
        :param z: The z coordinate of the block to ask.
        :return: A dictionary of the block data.
        """

        return LazyRequest(self.connection, "get block", {"x": x, "y": y, "z": z}, required_type=ord('n'), raw=True, modifier=lambda data: data.unpack())


    def list_loaded_chunks(self) -> LazyRequest[List]:
        """ Returns a list of loaded chunks."""

        return cast(LazyRequest[List],  LazyRequest(self.connection, "list loaded chunks", modifier=lambda data: data.get("chunks")))

    def click_slot(self, slot : int, button : int, action : SlotActionType) -> LazyRequest[dict]:
        """
        Simulates a single slot click/action. This is a low level function, slot ids change
        based on the current screen.

        Actions in the inventory are a determined by combinations of the button
        and the actions.

        See: https://minecraft.wiki/w/Java_Edition_protocol/Packets#Click_Container

        :param slot: Slot id, depends on current inventory.
        :param button: See wiki
        :param action: See wiki
        """

        return LazyRequest(self.connection, "click slot", {
            "slot": slot,
            "button": button,
            "action": action.value
        })
    def swap_slots(self, slot1 : int, slot2 : int, useOffhand : bool = False) -> LazyRequest[dict]:
        """
        Attempts to swap slots in an inventory. Either with clicking, or with offhand swaps.

        When useOffhand is set to false, will click slot1, then slot2, then slot1 again. This
        will not avoid merging of the same item type.

        When useOffhand is set to true, will swap slot1 with the offhand, then slot2, then slot1.
        This gets the same result, but avoids merging items, **however** may look suspicious.

        :param slot1: Slot id, depends on current inventory.
        :param slot2: Slot id, depends on current inventory.
        :param useOffhand: Use the offhand instead of clicking.
        :return:
        """

        return LazyRequest(self.connection, "swap slots", {
            "slot1": slot1,
            "slot2": slot2,
            "useOffhand": useOffhand
        })



    def get_player_inventory_contents(self):
        """ Returns JSON data of the player's inventory. Throws an error if a container is open"""
        return LazyRequest(self.connection, "get player inventory")

    def get_player_inventory(self) -> LazyRequest["PlayerInventory"]:
        """ Returns an object of the player's inventory. Throws an error if a container is open"""

        return self.get_player_inventory_contents().map(
            lambda inventory:
                PlayerInventory(self, inventory["slots"], inventory["name"]))


    def get_open_inventory_contents(self):
        return LazyRequest(self.connection, "get open inventory")

    def click_container_button(self, button: int):
        return LazyRequest(self.connection, "click inventory button", {"button": button})

    def get_merchant_trades(self):
        return LazyRequest(self.connection, "get trades")

    def select_trade(self, index: int):
        return LazyRequest(self.connection, "select trade", {"index": index})

    def set_anvil_name(self, name: str):
        return LazyRequest(self.connection, "set anvil name", {"name": name})

    def set_beacon_effect(self, primary: str | None, secondary: str | None = None):
        return LazyRequest(self.connection, "set beacon effect", {
            **({} if primary is None else {"primary": primary}),
            **({} if secondary is None else {"secondary": secondary})
        })

    def get_enchantments(self):
        return LazyRequest(self.connection, "get enchantments")

    def get_chunk(self, cx: int, cz: int) -> LazyRequest[Chunk]:
        """
        Asks for a specific chunk somewhere in the world.
        :param cx: Location of the chunk, note this is 16x smaller than the normal coordinates
        :param cz: Location of the chunk, note this is 16x smaller than the normal coordinates

        :return: On success, a Chunk object, or raises an error
        """
        
        return LazyRequest(self.connection, "get chunk", {"cx": cx, "cz": cz},
                            raw=True, required_type=ord('b'), modifier=lambda data: Chunk.from_network(BytesIO(data)))



    def search_for_blocks(self, blocks : Tuple[str] | List[str] | str):
        """
        Finds all the blocks of a certain type/types somewhere in the players render distance.
        This is MUCH faster than getting the entire world with ``get_chunk()``
        Note: Ids are in the form: ``minecraft:grass_block``


        :param blocks: A list of strings, or a single string
        :return: On success, a list of blocks
        """
        if type(blocks) is str:
            blocks = (blocks, )
        return LazyRequest(self.connection, "search for blocks", {"blocks": blocks})

    # =========================
    #   World/Server Management
    # =========================

    def get_server_list(self):
        """ Gets all the multiplayer servers in your server list, along with the "hidden" ones (your direct connect history). """
        return LazyRequest(self.connection, "get server list")

    def get_world_list(self):
        """
        List ALL the worlds on this minecraft instances .minecraft folder.

        This can be slow on some installs, as some users may have **thousands** of worlds.
        """
        return LazyRequest(self.connection, "get worlds")

    def join_world(self, name: str):
        """
        Joins a local world. The name **needs** to be from the 'load name' from getWorldList()

        :param name: The name of the world to join, **needs** to match the 'load name' from ``getWorldList()``
        """
        return LazyRequest(self.connection, "join world", {"load world": name})

    def join_server(self, address: str):
        """
        Joins a multiplayer server

        :param address: Server ip to connect to
        """
        return LazyRequest(self.connection, "join server", {"address": address})

    # =========================
    #   Player State Queries
    # =========================

    def get_freecam_state(self) -> LazyRequest[bool]:
        """ Tells you if freecam is currently enabled. """
        return cast(LazyRequest[bool], LazyRequest(self.connection, "is freecam", modifier=lambda data: data.get("is freecam")))

    def get_freerot_state(self) -> LazyRequest[bool]:
        """ Tells you if freeroot is currently enabled. """
        return cast(LazyRequest[bool], LazyRequest(self.connection, "is freerot", modifier=lambda data: data.get("is freerot")))

    def get_no_walk_state(self) -> LazyRequest[bool]:
        """ Tells you if no walk is currently enabled. """
        return cast(LazyRequest[bool], LazyRequest(self.connection, "is nowalk", modifier=lambda data: data.get("is nowalk")))

    def get_headless_state(self) -> LazyRequest[bool]:
        """ Tells your if the client is currently headless. """
        return cast(LazyRequest[bool], LazyRequest(self.connection, "is headless", modifier=lambda data: data.get("is headless")))

    # =========================
    #   Player State Setters
    # =========================

    def set_freecam(self, enabled: bool = True) -> LazyRequest[dict]:
        """ Set if freecam is currently enabled. """
        return LazyRequest(self.connection, "set freecam", {"enabled": enabled})

    def set_freerot(self, enabled: bool = True) -> LazyRequest[dict]:
        """ Set if freeroot is currently enabled. """
        return LazyRequest(self.connection, "set freerot", {"enabled": enabled})

    def set_no_walk(self, enabled: bool = True) -> LazyRequest[dict]:
        """ Set if no walk is currently enabled. """
        return LazyRequest(self.connection, "set nowalk", {"enabled": enabled})

    def set_headless(self, enabled: bool = True) -> LazyRequest[dict]:
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
        return LazyRequest(self.connection, "set headless", {"enabled": enabled})

    # =========================
    #   Baritone/Automation
    # =========================

    def baritone_goto(self, x: int, y: int, z: int) -> LazyRequest[dict]:
        """
        Tells baritone to go to a specific location.

        :param x: The x coordinate
        :param y: The y coordinate
        :param z: The z coordinate
        """
        return LazyRequest(self.connection, 
            "baritone goto", {"x": x, "y": y, "z": z}
        )

    # =========================
    #   Chat/Command Messaging
    # =========================

    def send_chat_message(self, message: str) -> LazyRequest[dict]:
        """
        Sends a public chat message. If prepended with "/", will execute a command.

        :param message: The message to send.
        """
        return LazyRequest(self.connection, 
            "send chat message", {"message": message}
        )

    def send_execute_command(self, message: str) -> LazyRequest[dict]:
        """
        Runs a command.

        :param message: The command to execute

        Note: Do **NOT** include the "/"

        Ex: ``gamemode creative`` to set the gamemode to creative.
        """
        return LazyRequest(self.connection, 
            "execute command", {"message": message}
        )

    def display_message(self, message: str) -> LazyRequest[dict]:
        """
        Displays a message in chat. This is private
        :param message:  Message to display in chat
        """
        return LazyRequest(self.connection, 
            "display chat message", {"message": message}
        )

    def overview_message(self, message: str) -> LazyRequest[dict]:
        """
        Shows a message above the users hotbar, this is great for informational status updates.

        For example, telling the user when something is starting and ending.

        :param message: Message to display above the hotbar
        """
        return LazyRequest(self.connection, 
            "overview message", {"message": message}
        )

    # =========================
    #   Input/Control
    # =========================

    def clear_inputs(self) -> LazyRequest[dict]:
        """ Remove all forced button presses. """
        return LazyRequest(self.connection, "clear force input")

    def get_forced_inputs(self) -> LazyRequest[dict]:
        """
        Reports the state of if certain input methods are forced. A key not being present
        indicates that no input is being forced. If a key is set to false, it is being forced up.
        And if a key is set to true, it is forced down.
        """
        return LazyRequest(self.connection, "get forced input", modifier=lambda data: data.get("inputs"))

    def force_inputs(self, inputs: List[Tuple[InputButton, bool]]) -> LazyRequest[dict]:
        """
        Force down/up buttons. If a button is not mentioned, it will not be impacted. Meaning that if it is already pressed,
        it will still be pressed if you do not update its state.

        :param inputs: List of tuples of (InputButton, bool). Where the bool is the **forced state** of the input. Meaning
                       setting to False indicates the **user cannot press** that key.
        """
        return LazyRequest(self.connection, 
            "force inputs",
            {
                "inputs": {
                    k[0].value: k[1] for k in inputs
                }
            },
        )

    def remove_forced_inputs(self, inputs: List[InputButton]) -> LazyRequest[dict]:
        """
        Disables the forced state of inputs. If a button is not mentioned, it will not be impacted.
        A complete list of inputs will result in identical behavior to ``clear_inputs()``

        :param inputs: A list if inputs, each input will have is state no longer controlled.
        """
        return LazyRequest(self.connection, 
            "force inputs",
            {
                "remove": [k.value for k in inputs]
            },
        )

    # =========================
    #   Player Movement/Rotation
    # =========================

    def arotate(
            self,
            pitch: float,
            yaw: float,
            speed: float = 3,
            method: RoMethod = RoMethod.LINEAR,
    ) -> LazyRequest[dict]:
        """
        Smoothly, and realistically, rotate the player.

        :param pitch: Pitch angle in degrees.
        :param yaw: Yaw angle in degrees.
        :param speed: Speed of rotation. This can be generally interpreted as `degrees per tick`, but with certain rotation methods
                      this will not be true.
        :param method: What interpolation method is used. This will not change the time required to rotate, but instead how it looks.
        """

        assert method != RoMethod.INSTANT, "Not a supported rotation method."

        return LazyRequest(self.connection, 
            "algorithmic rotation",
            {
                "pitch": pitch,
                "yaw": yaw,
                "degrees per tick": speed,
                "interpolation": method.value,
            },
        )

    def irotate(self, pitch: float, yaw: float) -> LazyRequest[dict]:
        """
        Instantly set the player's rotation. This looks like you are cheating.

        :param pitch: Pitch angle in degrees.
        :param yaw: Yaw angle in degrees.
        """
        return LazyRequest(self.connection, 
            "instantaneous rotation",
            {
                "pitch": pitch,
                "yaw": yaw,
            },
        )

    def set_hotbar_slot(self, slot: int) -> LazyRequest[dict]:
        """
        Set the current hotbar slot.

        :param slot: [1, 9] are valid hotbar slots
        """
        assert 1 <= slot <= 9, "Invalid slot value"
        return LazyRequest(self.connection, "set hotbar slot", {"slot": slot})

    def attack(self) -> LazyRequest[dict]:
        """ Tells the player to punch. Single left click """
        return LazyRequest(self.connection, "attack key click")

    def use(self) -> LazyRequest[dict]:
        """ Tells the player to use an item/block. Single right click """
        return LazyRequest(self.connection, "use key click")

    def auto_use(self,
                       x : int, y  : int, z : int,
                       speed : float = 3, method : RoMethod = RoMethod.LINEAR,
                       direction_of_use : Direction | None = None
                 ) -> LazyRequest[dict]:
        """
        Look at block and click it.

        :param x: X location of block
        :param y: Y location of block
        :param z: Z location of block
        :param speed: Degrees per tick speed of rotation
        :param method: Rotation method
        :param direction_of_use: What direction of the block to clic
        :return:
        """

        return LazyRequest(self.connection, "auto use", {
            "x": x, "y": y, "z": z,
            "degrees per tick": speed,
            "method": method.value,
            **({} if direction_of_use is None else {"direction" : direction_of_use.value})
        })

    def auto_place(self,
                         x: int, y: int, z: int,
                         speed : float = 3, method : RoMethod = RoMethod.LINEAR,
                         direction_to_place_on : Direction | None = None
                         ) -> LazyRequest[dict]:
        """
        Place a block

        :param x: X location of block to place
        :param y: Y location of block to place
        :param z: Z location of block to place
        :param speed: Degrees per tick speed of rotation
        :param method: Rotation method
        :param direction_to_place_on: What block to place on. For example, use down to
                                      place on the block UNDER the location you specify
        """
        return LazyRequest(self.connection, "auto place", {
            "x": x, "y": y, "z": z,
            "degrees per tick": speed,
            "method": method.value,
            **({} if direction_to_place_on is None else {"direction" : direction_to_place_on.value})
        })

    def set_directional_walk(
            self, degrees: float, speed: float = 1, force: bool = False
    )-> LazyRequest[dict]:
        """
        Force the player to walk in a certain direction. Directional walking allows you to make the player walk towards a block.
        The direction the player is walking in is absolute, meaning the user can look around without interfacing.

        :param degrees: The **global** direction, in degrees, from 0-360, of where the user will walk.
        :param speed: Should be from 0-1. With zero being no movement, and one being regular walk speed.
        :param force: If false, will clamp the speed. If true, will allow any speed value, basically being speed hacks.
        """
        return LazyRequest(self.connection, 
            "set directional movement degree",
            {
                "direction": degrees,
                "speed": speed,
                "force": force,
            },
        )

    def set_directional_walk_vector(
            self, x: float, z: float, speed: float = 1, force: bool = False
    ) -> LazyRequest[dict]:
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
        return LazyRequest(self.connection, 
            "set directional movement vector",
            {
                "x": x,
                "z": z,
                "speed": speed,
                "force": force,
            },
        )

    def stop_directional_walk(self) -> LazyRequest[dict]:
        """No longer be directional walking"""
        return LazyRequest(self.connection, "clear directional movement")


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

    def __init__(self, player: Player, slot_data, screen_name: str | None = None, horse_data: Dict | None = None):
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

    def set_name(self, name: str) -> LazyRequest[dict]:
        return self.player.set_anvil_name(name)


class Grindstone(Generic2Input):
    container_type = "grindstone"


class Merchant(Generic2Input):
    container_type = "merchant"

    def get_trades(self) -> LazyRequest[dict]:
        return self.player.get_merchant_trades()

    def select_trade(self, index: int) -> LazyRequest[dict]:
        return self.player.select_trade(index)


class CartographyTable(Generic2Input):
    container_type = "cartography_table"


class Beacon(Inventory):
    container_type = "beacon"
    player_inventory_offset = 1

    def get_payment_slot(self):
        return self.get_slot(0)

    def set_effects(self, primary: None | str = None, secondary: None | str = None) -> LazyRequest[dict]:
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

    def get_potion_output(self, index=0):
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

    def get_enchants(self) -> LazyRequest[dict]:
        return self.player.get_enchantments()

    def select_enchantment(self, index: int) -> LazyRequest[dict]:
        assert 0 <= index <= 2

        return self.player.click_container_button(index)


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

    def __init__(self, player: Player, slot_data, screen_name: str | None = None, horse_data=None):
        assert horse_data is not None

        self.container_height = 3
        self.container_width = horse_data["inventory cols"]

        self.player_inventory_offset = 2 + 3 * self.container_height

        super().__init__(player, slot_data, screen_name, horse_data=horse_data)

    def get_saddle(self):
        return self.get_slot(0)

    def get_armor(self):
        return self.get_slot(1)
