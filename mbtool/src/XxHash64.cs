// xxHash64 (XXH64) - port of the reference algorithm, seed 0.
// Bannerlord stores, per asset in a .tpac, an 8-byte little-endian hash of the
// asset's metadata *as written to disk*, i.e. XXH64( u64le(metaLen) || metadata ).
using System;

namespace TpacTool.Lib
{
	public static class XxHash64
	{
		private const ulong P1 = 11400714785074694791UL;
		private const ulong P2 = 14029467366897019727UL;
		private const ulong P3 = 1609587929392839161UL;
		private const ulong P4 = 9650029242287828579UL;
		private const ulong P5 = 2870177450012600261UL;

		private static ulong Rotl(ulong x, int r) => (x << r) | (x >> (64 - r));

		private static ulong Round(ulong acc, ulong input)
		{
			acc += input * P2;
			acc = Rotl(acc, 31);
			acc *= P1;
			return acc;
		}

		private static ulong MergeRound(ulong acc, ulong val)
		{
			val = Round(0, val);
			acc ^= val;
			acc = acc * P1 + P4;
			return acc;
		}

		public static ulong Hash(byte[] data, int offset, int length, ulong seed = 0)
		{
			int i = offset;
			int end = offset + length;
			ulong h;

			if (length >= 32)
			{
				ulong v1 = seed + P1 + P2;
				ulong v2 = seed + P2;
				ulong v3 = seed;
				ulong v4 = seed - P1;

				int limit = end - 32;
				do
				{
					v1 = Round(v1, ReadU64(data, i)); i += 8;
					v2 = Round(v2, ReadU64(data, i)); i += 8;
					v3 = Round(v3, ReadU64(data, i)); i += 8;
					v4 = Round(v4, ReadU64(data, i)); i += 8;
				} while (i <= limit);

				h = Rotl(v1, 1) + Rotl(v2, 7) + Rotl(v3, 12) + Rotl(v4, 18);
				h = MergeRound(h, v1);
				h = MergeRound(h, v2);
				h = MergeRound(h, v3);
				h = MergeRound(h, v4);
			}
			else
			{
				h = seed + P5;
			}

			h += (ulong)length;

			while (i + 8 <= end)
			{
				ulong k1 = Round(0, ReadU64(data, i));
				h ^= k1;
				h = Rotl(h, 27) * P1 + P4;
				i += 8;
			}

			if (i + 4 <= end)
			{
				h ^= (ulong)ReadU32(data, i) * P1;
				h = Rotl(h, 23) * P2 + P3;
				i += 4;
			}

			while (i < end)
			{
				h ^= data[i] * P5;
				h = Rotl(h, 11) * P1;
				i++;
			}

			h ^= h >> 33;
			h *= P2;
			h ^= h >> 29;
			h *= P3;
			h ^= h >> 32;
			return h;
		}

		public static ulong Hash(byte[] data, ulong seed = 0) => Hash(data, 0, data.Length, seed);

		/// <summary>
		/// The exact hash Bannerlord stores next to each asset in a .tpac:
		/// XXH64( u64le(metadata.Length) || metadata ).
		/// </summary>
		public static ulong HashMetadata(byte[] metadata)
		{
			var buffer = new byte[8 + metadata.Length];
			ulong len = (ulong) metadata.Length;
			for (int i = 0; i < 8; i++)
				buffer[i] = (byte) (len >> (8 * i));
			Array.Copy(metadata, 0, buffer, 8, metadata.Length);
			return Hash(buffer, 0, buffer.Length, 0);
		}

		private static ulong ReadU64(byte[] b, int i) =>
			(ulong)b[i] | ((ulong)b[i + 1] << 8) | ((ulong)b[i + 2] << 16) | ((ulong)b[i + 3] << 24) |
			((ulong)b[i + 4] << 32) | ((ulong)b[i + 5] << 40) | ((ulong)b[i + 6] << 48) | ((ulong)b[i + 7] << 56);

		private static uint ReadU32(byte[] b, int i) =>
			(uint)b[i] | ((uint)b[i + 1] << 8) | ((uint)b[i + 2] << 16) | ((uint)b[i + 3] << 24);
	}
}
