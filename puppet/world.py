import nbtlib

from io import BytesIO
import struct

# See: me.psychedelicpalimpsest.commands.world.GetChunk#serializeSimple
#      in the mod for more info on palette the structure. 

class Section:
    """
        Represents 16 x 16 x 16 logical sections of minecraft chunks. It is read only,
        and holds data internally in a custom format that the mods spits out.
    """



    def __init__(self, bit_length, edge_bits, palette, longs):
        self.bit_length = bit_length
        self.palette = palette
        self.edge_bits = edge_bits

        self.longs = longs


    def _get_raw_id(self, sx : int, sy : int, sz : int):
        # A section filled with one type
        if self.bit_length == 0:
            return 0

        # This math hurts my head
        blockIndex = (sy << self.edge_bits | sz) << self.edge_bits | sx
        bitIndex = blockIndex * self.bit_length

        num = self.longs[bitIndex // 64]

        if (bitIndex + self.bit_length) // 64 != bitIndex // 64:
            num |= self.longs[(bitIndex + self.bit_length) // 64] << 64

        return (num  >> (bitIndex % 64) ) & ((1 << self.bit_length) - 1)

    def get_block_in_section(self, sx : int, sy : int, sz : int):
        return self.palette[self._get_raw_id(sx, sy, sz)]



    @classmethod
    def from_network(cls, reader : BytesIO):
        # Section format: [short: Bits per block][int: amount of longs][byte: nbt tag type][nbt: palette][array of longs]
        bitSize, edgeBits, longCount = struct.unpack("!hhi", reader.read(8))

        # Minecraft network nbt is prefixed with a type, which breaks
        # the nbt reader unless we consume it.
        assert nbtlib.List.tag_id == reader.read(1)[0]

        palette = nbtlib.List.parse(reader).unpack()

        longs = struct.unpack(f"!{longCount}Q", reader.read(longCount*8))
        
        return cls(bitSize, edgeBits,  palette, longs)



class Chunk:
    """ 
        Represents minecrafts 16 x ? x 16 chunks. It is a read only structure.
        
    """
    def __init__(self, block_entities, section_bottom, section_top, sections):
        self.block_entities = block_entities
        self.section_top = section_top
        self.section_bottom = section_bottom
        self.sections = sections
    @classmethod
    def from_network(cls, reader : BytesIO):
        """ Decode a chunk from the network """
        assert nbtlib.List.tag_id == reader.read(1)[0]

        # Chunk format: [byte: nbt tag type][nbt: block entites][int: section bottom][int: section top][short: section count][sections]

        block_entities = nbtlib.List.parse(reader).unpack()

        sections = []

        section_bottom, section_top, section_len = struct.unpack("!iih", reader.read(2 + 4 + 4))
        
        for i in range(section_len):
            sections.append(Section.from_network(reader))
        
        return cls(block_entities, section_bottom, section_top, sections)

    def get_block_in_chunk(self, cx : int, cy : int, cz : int):
        """
            Get a block based off its coordinates within the chunk. Throws
            assertion errors if you give it invalid args.

            :param cx: X within chunk
            :param cy: Y component, due to how minecraft works, this is also the typical y cordinate.
            :param cz: Y within chunk

        """

        sectiony = cy // 16
        assert self.section_bottom <= sectiony < self.section_top
        assert 0 <= cx < 16
        assert 0 <= cz < 16

        return self.sections[sectiony - self.section_bottom].get_block_in_section(cx, cy % 16, cz)




