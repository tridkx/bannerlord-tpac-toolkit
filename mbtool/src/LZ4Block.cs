// Self-contained LZ4 block-format codec, replacing the lz4net NuGet dependency.
// Bannerlord's tpac data segments use raw LZ4 *block* format (no frame header).
using System;
using System.Collections.Generic;

namespace LZ4
{
	public static class LZ4Codec
	{
		/// <summary>Decode a raw LZ4 block into exactly <paramref name="outputLength"/> bytes.</summary>
		public static byte[] Decode(byte[] input, int offset, int length, int outputLength)
		{
			var dst = new byte[outputLength];
			int sp = offset;
			int send = offset + length;
			int dp = 0;

			while (sp < send)
			{
				int token = input[sp++];

				// ---- literal run ----
				int litLen = token >> 4;
				if (litLen == 15)
				{
					int b;
					do
					{
						if (sp >= send) throw new InvalidOperationException("truncated LZ4 literal length");
						b = input[sp++];
						litLen += b;
					} while (b == 255);
				}

				if (litLen > 0)
				{
					if (sp + litLen > send) throw new InvalidOperationException("truncated LZ4 literals");
					if (dp + litLen > outputLength) throw new InvalidOperationException("LZ4 output overflow");
					Buffer.BlockCopy(input, sp, dst, dp, litLen);
					sp += litLen;
					dp += litLen;
				}

				if (dp >= outputLength)
					break; // last sequence: literals only, no match

				// ---- match copy ----
				if (sp + 2 > send) throw new InvalidOperationException("truncated LZ4 match offset");
				int matchOffset = input[sp] | (input[sp + 1] << 8);
				sp += 2;
				if (matchOffset == 0) throw new InvalidOperationException("invalid LZ4 match offset 0");

				int matchLen = token & 0x0F;
				if (matchLen == 15)
				{
					int b;
					do
					{
						if (sp >= send) throw new InvalidOperationException("truncated LZ4 match length");
						b = input[sp++];
						matchLen += b;
					} while (b == 255);
				}
				matchLen += 4;

				int mp = dp - matchOffset;
				if (mp < 0) throw new InvalidOperationException("LZ4 match before start of output");
				if (dp + matchLen > outputLength) throw new InvalidOperationException("LZ4 output overflow (match)");

				// byte-by-byte: matches may overlap the current position
				for (int i = 0; i < matchLen; i++)
					dst[dp++] = dst[mp++];
			}

			if (dp != outputLength)
				throw new InvalidOperationException($"LZ4 produced {dp} bytes, expected {outputLength}");

			return dst;
		}

		/// <summary>
		/// Greedy hash-table LZ4 block compressor. Not the best ratio, but produces a
		/// standard block that any LZ4 decoder (including the game engine) accepts.
		/// </summary>
		public static byte[] EncodeHC(byte[] input, int offset, int length)
		{
			return Encode(input, offset, length);
		}

		public static byte[] Encode(byte[] input, int offset, int length)
		{
			const int MIN_MATCH = 4;
			const int LAST_LITERALS = 5;
			const int MF_LIMIT = 12;
			const int HASH_LOG = 16;
			const int HASH_SIZE = 1 << HASH_LOG;
			const int MAX_DISTANCE = 65535;

			var output = new List<byte>(length + (length / 255) + 16);
			var table = new int[HASH_SIZE];
			for (int i = 0; i < HASH_SIZE; i++) table[i] = -1;

			int anchor = offset;
			int ip = offset;
			int iend = offset + length;
			int mflimit = iend - MF_LIMIT;

			if (length >= MF_LIMIT)
			{
				while (ip < mflimit)
				{
					uint seq = ReadU32(input, ip);
					int h = (int)((seq * 2654435761u) >> (32 - HASH_LOG));
					int candidate = table[h];
					table[h] = ip;

					if (candidate < 0 || ip - candidate > MAX_DISTANCE ||
						ReadU32(input, candidate) != seq)
					{
						ip++;
						continue;
					}

					// extend match
					int matchLen = 0;
					int maxLen = iend - LAST_LITERALS - ip;
					while (matchLen < maxLen && input[candidate + matchLen] == input[ip + matchLen])
						matchLen++;

					if (matchLen < MIN_MATCH)
					{
						ip++;
						continue;
					}

					// emit sequence
					int litLen = ip - anchor;
					int tokenPos = output.Count;
					output.Add(0);
					int token = 0;

					if (litLen >= 15)
					{
						token |= 0x0F << 4;
						int rem = litLen - 15;
						while (rem >= 255) { output.Add(255); rem -= 255; }
						output.Add((byte)rem);
					}
					else
					{
						token |= litLen << 4;
					}
					for (int i = 0; i < litLen; i++) output.Add(input[anchor + i]);

					int matchCode = matchLen - MIN_MATCH;
					if (matchCode >= 15)
						token |= 0x0F;
					else
						token |= matchCode;

					// LZ4 order: token, [literal-length ext], literals, offset, [match-length ext]
					int offs = ip - candidate;
					output.Add((byte)(offs & 0xFF));
					output.Add((byte)((offs >> 8) & 0xFF));

					if (matchCode >= 15)
					{
						int rem = matchCode - 15;
						while (rem >= 255) { output.Add(255); rem -= 255; }
						output.Add((byte)rem);
					}

					output[tokenPos] = (byte)token;

					ip += matchLen;
					anchor = ip;
				}
			}

			// final literal run
			{
				int litLen = iend - anchor;
				int tokenPos = output.Count;
				output.Add(0);
				int token = 0;
				if (litLen >= 15)
				{
					token |= 0x0F << 4;
					int rem = litLen - 15;
					while (rem >= 255) { output.Add(255); rem -= 255; }
					output.Add((byte)rem);
				}
				else
				{
					token |= litLen << 4;
				}
				for (int i = 0; i < litLen; i++) output.Add(input[anchor + i]);
				output[tokenPos] = (byte)token;
			}

			return output.ToArray();
		}

		private static uint ReadU32(byte[] b, int i)
		{
			return (uint)(b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24));
		}
	}
}
