from connection import *
import asyncio


class Player:
    async def _callback_handler(self, info):
        print(info)

    def __init__(self, connection: ClientConnection):
        self.connection = connection
        self.connection.callback_handler = self._callback_handler

    def handle_json(self, packet_type: int, json: dict) -> dict:
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
        return self.handle_json( *await self.connection.write_packet(message, extra) )

    @classmethod
    async def discover(cls, with_name=None):
        async for broadcast, (host, _) in gen_broadcasts():
            if with_name is not None and broadcast["player username"] != with_name:
                continue

            connection = ClientConnection(host, broadcast["port"])
            await connection.start()
            return cls(connection)

        assert False, "Unreachable"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.connection.__aexit__(exc_type, exc, tb)

    # ========================================
    #        Informational functions
    # ========================================

    async def get_client_info(self):
        """ Returns a dictionary of a bunch of information about the game client """
        return await self.handle_packet("client info")

    async def get_installed_mods(self):
        return (await self.handle_packet("get mod list")).get("mods")

    async def get_callback_states(self) -> dict[CallbackType, bool]:
        """ Tells you what callbacks are currently enabled in the client. Use ``set_callbacks()`` to enable them. """
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

    # ========================================
    #           World/server functions
    # ========================================

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

    async def baritone_goto(self, x: int, y: int, z: int):
        """  Tells baritone to go to a specific location. """
        return await self.handle_packet(
            "baritone goto", {"x": x, "y": y, "z": z}
        )

    async def get_freecam_state(self) -> bool:
        """ Tells you if freecam is currently enabled. """
        return (await self.handle_packet("is freecam"))["is freecam"]

    async def get_freerot_state(self) -> bool:
        """ Tells you if freeroot is currently enabled. """
        return (await self.handle_packet("is freerot"))["is freerot"]

    async def get_no_walk_state(self) -> bool:
        """ Tells you if no walk is currently enabled. """
        return (await self.handle_packet("is nowalk"))["is nowalk"]

    async def set_freecam(self, enabled: bool = True):
        """ Set if freecam is currently enabled. """
        return await self.handle_packet("set freecam", {"enabled": enabled})

    async def set_freerot(self, enabled: bool = True):
        """ Set if freeroot is currently enabled. """
        return await self.handle_packet("set freerot", {"enabled": enabled})

    async def set_no_walk(self, enabled: bool = True):
        """ Set if no walk is currently enabled. """
        return await self.handle_packet("set nowalk", {"enabled": enabled})

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

    # Player control
    async def clear_inputs(self):
        """ Remove all forced button presses. """
        return await self.handle_packet("clear force input")

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
        :param speed: Speed of rotation. Thi
        """
        return await self.handle_packet(
            "instantaneous rotation",
            {
                "pitch": pitch,
                "yaw": yaw,
            },
        )

    async def attack(self):
        """
        Tells the player to punch. Single left click
        """
        return await self.handle_packet("attack key click")

    async def use(self):
        """
        Tells the player to use an item/block. Single right click
        """
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
