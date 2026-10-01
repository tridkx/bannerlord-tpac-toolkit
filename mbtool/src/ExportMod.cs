using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text;
using TpacTool.Lib;

namespace MbTool
{
	/// <summary>
	/// exportmod —— 把一个 .tpac 里的**整套资产**掏出来（网格 + 材质 + 贴图），
	/// 供离线预览器直接使用，不需要那个 mod 的工程目录（work/posed 之类）。
	///
	/// 为什么需要它
	/// ------------
	/// 预览器原先只能吃"已重定向到 BL 骨架"的工程中间产物 `work/posed/*.npz`，
	/// 于是有两个后果：
	///   1. 打不开别人的 mod，也打不开自己最终交付的那个 pack0.tpac；
	///   2. 离线验证的是中间产物，**不是最终交付的那个文件** —— 打包环节
	///      （权重量化、.mgeo 同名覆盖……）出的问题它一个也看不见。
	/// exportmod 从**最终产物倒推**，绕开这两条。
	///
	/// 分工
	/// ----
	/// 这里只负责"把 tpac 里的字节原样掏出来"（几何二进制 + 清单 JSON + 贴图原始
	/// BC 数据）。解码 BC / 组装成可渲染格式由 Python 侧做 —— 消费方是配套项目
	/// bannerlord-anim-previewer（baker/geometry.py 与 baker/material.py），
	/// 那边有现成的 BC 解码器（本仓库 py/bcencode.py）和 PIL，比在 C# 里重写一遍可靠。
	///
	/// 用法
	/// ----
	///   mbtool exportmod &lt;pack.tpac&gt; &lt;outDir&gt; [lod] [--all-mips]
	///     lod        只导出该 lod（缺省：每个 metamesh 取自己最小的 lod）
	///     --all-mips 贴图连 mip 链一起导出（缺省只导 mip0，预览够用且省 1/3 体积）
	/// </summary>
	public static class ExportMod
	{
		private const uint GEO_MAGIC = 0x424D4447;   // 'GDMB' little endian
		private const uint GEO_VERSION = 1;

		public static int Run(string[] a)
		{
			if (a.Length < 3)
			{
				Console.Error.WriteLine("usage: exportmod <pack.tpac> <outDir> [lod] [--all-mips]");
				return 1;
			}

			string packPath = a[1];
			string outDir = a[2];
			int wantLod = -1;
			bool allMips = false;
			for (int i = 3; i < a.Length; i++)
			{
				if (a[i] == "--all-mips") { allMips = true; continue; }
				if (a[i].StartsWith("--")) { Console.Error.WriteLine("unknown option " + a[i]); return 1; }
				if (!int.TryParse(a[i], out wantLod)) { Console.Error.WriteLine("bad lod: " + a[i]); return 1; }
			}

			var pkg = new AssetPackage(packPath, true, true);

			var matByGuid = new Dictionary<Guid, Material>();
			foreach (var m in pkg.Items.OfType<Material>()) matByGuid[m.Guid] = m;
			var texByGuid = new Dictionary<Guid, Texture>();
			foreach (var t in pkg.Items.OfType<Texture>()) texByGuid[t.Guid] = t;

			string geoDir = Path.Combine(outDir, "geo");
			string texDir = Path.Combine(outDir, "tex");
			Directory.CreateDirectory(geoDir);
			Directory.CreateDirectory(texDir);

			var sb = new StringBuilder();
			var usedGeo = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
			var usedTex = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

			// ---------------- 网格 ----------------
			var meshJsons = new List<string>();
			var lodPerMesh = new SortedDictionary<string, int>(StringComparer.Ordinal);
			var lodByMesh = new Dictionary<string, int>();
			int meshOk = 0, subTotal = 0, vertTotal = 0, triTotal = 0, skippedNoStream = 0, skippedNoLod = 0;
			int lastLodUsed = -1;

			var allMeshes = pkg.Items.OfType<Metamesh>()
				.OrderBy(x => x.Name, StringComparer.Ordinal).ToList();
			foreach (var kv in allMeshes.Where(x => x.Meshes != null && x.Meshes.Count > 0)
				.ToDictionary(x => x.Name, x => wantLod >= 0 ? wantLod : x.Meshes.Min(y => y.Lod)))
				lodPerMesh[kv.Key] = kv.Value;
			foreach (var mm in allMeshes)
			{
				if (mm.Meshes == null || mm.Meshes.Count == 0) continue;

				int lod = wantLod >= 0 ? wantLod : mm.Meshes.Min(x => x.Lod);
				var subs = mm.Meshes.Where(x => x.Lod == lod).ToList();
				if (subs.Count == 0)
				{
					skippedNoLod++;
					Console.WriteLine($"  ! {mm.Name}: 没有 lod {lod}（可选 lod: " +
						string.Join(",", mm.Meshes.Select(x => x.Lod).Distinct().OrderBy(x => x)) + "），已跳过");
					continue;
				}

				var usable = new List<Mesh>();
				foreach (var s in subs)
				{
					var vs = s.VertexStream?.Data;
					if (vs == null || vs.Positions == null || vs.Positions.Length == 0) { skippedNoStream++; continue; }
					usable.Add(s);
				}
				if (usable.Count == 0) continue;

				lastLodUsed = lod;
				lodByMesh[mm.Name] = lod;
				string fname = UniqueName(usedGeo, Sanitize(mm.Name)) + ".bin";
				string fpath = Path.Combine(geoDir, fname);

				var subJsons = new List<string>();
				using (var fs = File.Create(fpath))
				using (var w = new BinaryWriter(fs))
				{
					w.Write(GEO_MAGIC);
					w.Write(GEO_VERSION);
					w.Write((uint)usable.Count);

					foreach (var s in usable)
					{
						var vs = s.VertexStream.Data;
						int n = vs.Positions.Length;
						int ni = vs.Indices?.Length ?? 0;

						// ★ 材质的 GUID **不一定**在 Mesh.Material 上：
					//   官方 Modding Kit 打出来的包（实测 LVBU and DIAOCHAN，215/215
					//   个子网格）把真正的材质放在 **SecondMaterial**，Material 是空 Guid。
					//   只看 Material 的话，pack.json 里材质全是空串、texmap 一条都建不起来，
					//   预览器只能退回"按名字猜贴图" ⇒ 整个 mod 的贴图都是错的。
					//   （本仓库自己的 exportmesh 是两个都写的，mataudit 也按 M/S 两种来源统计，
					//     只有 exportmod 漏了；别拿上游 TpacTool 的导出器当权威，它有同样的笔误。）
					var matDep = (s.Material != null && s.Material.Guid != Guid.Empty)
						? s.Material : s.SecondMaterial;
					string matName = MatName(matByGuid, matDep);

						w.Write(Utf8(s.Name ?? ""));
						w.Write(s.Lod);
						w.Write(Utf8(matName));
						w.Write(Ascii36(matDep?.Guid ?? Guid.Empty));
						w.Write((uint)n);
						w.Write((uint)ni);

						var bb = s.BoundingBox;
						w.Write(bb.Min.X); w.Write(bb.Min.Y); w.Write(bb.Min.Z);
						w.Write(bb.Max.X); w.Write(bb.Max.Y); w.Write(bb.Max.Z);

						uint flags = 0;
						if (vs.Normals != null && vs.Normals.Length == n) flags |= 1u;
						if (vs.Uv2 != null && vs.Uv2.Length == n) flags |= 2u;
						if (vs.Colors1 != null && vs.Colors1.Length == n) flags |= 4u;
						if (vs.Colors2 != null && vs.Colors2.Length == n) flags |= 8u;
						if (vs.Tangents != null && vs.Tangents.Length == n) flags |= 16u;
						if (vs.BoneIndices != null && vs.BoneIndices.Length == n) flags |= 32u;
						w.Write(flags);

						foreach (var p in vs.Positions) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); }
						if ((flags & 1u) != 0) foreach (var p in vs.Normals) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); }
						foreach (var p in vs.Uv1) { w.Write(p.X); w.Write(p.Y); }
						if ((flags & 2u) != 0) foreach (var p in vs.Uv2) { w.Write(p.X); w.Write(p.Y); }
						if ((flags & 4u) != 0) foreach (var p in vs.Colors1) { w.Write(p.R); w.Write(p.G); w.Write(p.B); w.Write(p.A); }
						if ((flags & 8u) != 0) foreach (var p in vs.Colors2) { w.Write(p.R); w.Write(p.G); w.Write(p.B); w.Write(p.A); }
						if ((flags & 16u) != 0) foreach (var p in vs.Tangents) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); w.Write(p.W); }
						if ((flags & 32u) != 0) foreach (var p in vs.BoneIndices) { w.Write(p.B1); w.Write(p.B2); w.Write(p.B3); w.Write(p.B4); }
						if (vs.BoneWeights != null) foreach (var p in vs.BoneWeights) { w.Write(p.W1); w.Write(p.W2); w.Write(p.W3); w.Write(p.W4); }
						if (ni > 0) foreach (var p in vs.Indices) w.Write(p);

						var usedBones = new SortedSet<int>();
						if (vs.BoneIndices != null)
							foreach (var bi in vs.BoneIndices)
							{
								usedBones.Add(bi.B1); usedBones.Add(bi.B2); usedBones.Add(bi.B3); usedBones.Add(bi.B4);
							}

						subJsons.Add(
							"      {\"index\": " + subJsons.Count + ", \"name\": \"" + Esc(s.Name) + "\", \"lod\": " + s.Lod +
							", \"material\": \"" + Esc(matName) + "\"" +
							", \"materialGuid\": \"" + (matDep?.Guid ?? Guid.Empty) + "\"" +
							", \"secondMaterialGuid\": \"" + (s.SecondMaterial?.Guid ?? Guid.Empty) + "\"" +
							", \"vertexCount\": " + n + ", \"indexCount\": " + ni +
							", \"triangleCount\": " + (ni / 3) +
							", \"hasSkin\": " + (((flags & 32u) != 0) ? "true" : "false") +
							", \"bonesUsed\": [" + string.Join(",", usedBones) + "]" +
							", \"bboxMin\": [" + F(bb.Min.X) + "," + F(bb.Min.Y) + "," + F(bb.Min.Z) + "]" +
							", \"bboxMax\": [" + F(bb.Max.X) + "," + F(bb.Max.Y) + "," + F(bb.Max.Z) + "]}");

						subTotal++; vertTotal += n; triTotal += ni / 3;
					}
				}

				meshOk++;
				meshJsons.Add(
					"    {\"name\": \"" + Esc(mm.Name) + "\", \"guid\": \"" + mm.Guid + "\"" +
					", \"lod\": " + lod + ", \"lodAvailable\": [" + string.Join(",", mm.Meshes.Select(x => x.Lod).Distinct().OrderBy(x => x)) + "]" +
					", \"submeshCount\": " + usable.Count +
					", \"bodyPart\": \"" + Esc(mm.UnknownString) + "\"" +
					", \"file\": \"geo/" + Esc(fname) + "\",\n     \"submeshes\": [\n" +
					string.Join(",\n", subJsons) + "\n     ]}");
			}

			// ---------------- 材质 ----------------
			var matJsons = new List<string>();
			foreach (var m in pkg.Items.OfType<Material>().OrderBy(x => x.Name, StringComparer.Ordinal))
			{
				var slots = new List<string>();
				foreach (var kv in m.Textures ?? new SortedDictionary<int, AssetDependence<Texture>>())
				{
					string tn = "";
					if (kv.Value != null && texByGuid.TryGetValue(kv.Value.Guid, out var t0)) tn = t0.Name;
					slots.Add("\"" + kv.Key + "\": \"" + Esc(tn) + "\"");
				}
				matJsons.Add(
					"    {\"name\": \"" + Esc(m.Name) + "\", \"guid\": \"" + m.Guid + "\"" +
					", \"blendMode\": \"" + Esc(m.BlendMode) + "\"" +
					", \"alphaTest\": " + F(m.AlphaTest) +
					", \"flags\": [" + StrList(m.Flags) + "]" +
					", \"shaderMatFlags\": [" + StrList(m.ShaderMaterialFlags) + "]" +
					", \"vertexLayoutFlags\": [" + StrList(m.VertexLayoutFlags) + "]" +
					", \"textures\": {" + string.Join(", ", slots) + "}}");
			}

			// ---------------- 贴图 ----------------
			var texJsons = new List<string>();
			long texBytes = 0;
			foreach (var t in pkg.Items.OfType<Texture>().OrderBy(x => x.Name, StringComparer.Ordinal))
			{
				var pix = t.TexturePixels?.Data;
				if (pix == null || pix.RawImage == null || pix.RawImage.Length == 0 || pix.RawImage[0] == null)
				{
					texJsons.Add("    {\"name\": \"" + Esc(t.Name) + "\", \"guid\": \"" + t.Guid + "\"" +
								 ", \"width\": " + t.Width + ", \"height\": " + t.Height +
								 ", \"mipCount\": " + (int)t.MipmapCount + ", \"format\": \"" + t.Format + "\"" +
								 ", \"error\": \"no pixel data\", \"file\": null}");
					continue;
				}

				string fname = UniqueName(usedTex, Sanitize(t.Name)) + ".bin";
				string fpath = Path.Combine(texDir, fname);
				var mips = pix.RawImage[0];
				int nMip = allMips ? mips.Length : Math.Min(1, mips.Length);
				var sizes = new List<int>();
				var offsets = new List<int>();

				using (var fs = File.Create(fpath))
				using (var w = new BinaryWriter(fs))
				{
					int off = 0;
					for (int i = 0; i < nMip; i++)
					{
						var b = mips[i] ?? new byte[0];
						offsets.Add(off);
						sizes.Add(b.Length);
						w.Write(b);
						off += b.Length;
					}
					texBytes += off;
				}

				texJsons.Add(
					"    {\"name\": \"" + Esc(t.Name) + "\", \"guid\": \"" + t.Guid + "\"" +
					", \"width\": " + t.Width + ", \"height\": " + t.Height +
					", \"mipCount\": " + (int)t.MipmapCount + ", \"mipsExported\": " + nMip +
					", \"arrayCount\": " + (int)t.ArrayCount +
					", \"format\": \"" + t.Format + "\"" +
					", \"source\": \"" + Esc(t.Source) + "\"" +
					", \"systemFlags\": [" + StrList(t.SystemFlags) + "]" +
					", \"flags\": [" + StrList(t.Flags) + "]" +
					", \"mipOffset\": [" + string.Join(",", offsets) + "]" +
					", \"mipSize\": [" + string.Join(",", sizes) + "]" +
					", \"file\": \"tex/" + Esc(fname) + "\"}");
			}

			// ---------------- 骨架（有些 mod 自带） ----------------
			var skelJsons = new List<string>();
			foreach (var s in pkg.Items.OfType<Skeleton>())
				skelJsons.Add("    {\"name\": \"" + Esc(s.Name) + "\", \"guid\": \"" + s.Guid + "\"}");

			// ---------------- 清单 ----------------
			sb.Append("{\n");
			sb.Append("  \"tool\": \"mbtool exportmod\",\n");
			sb.Append("  \"format\": 1,\n");
			sb.Append("  \"pack\": \"" + Esc(packPath) + "\",\n");
			sb.Append("  \"packGuid\": \"" + pkg.Guid + "\",\n");
			sb.Append("  \"requestedLod\": " + wantLod + ",\n");
			sb.Append("  \"lodUsed\": " + lastLodUsed + ",\n");
			sb.Append("  \"lodPerMesh\": {" + string.Join(",", lodPerMesh.Select(kv =>
				"\"" + Esc(kv.Key) + "\": " + kv.Value)) + "},\n");
			sb.Append("  \"stats\": {\"meshes\": " + meshOk + ", \"submeshes\": " + subTotal +
					  ", \"vertices\": " + vertTotal + ", \"triangles\": " + triTotal +
					  ", \"skippedNoVertexStream\": " + skippedNoStream + "},\n");
			sb.Append("  \"meshes\": [\n" + string.Join(",\n", meshJsons) + "\n  ],\n");
			sb.Append("  \"materials\": [\n" + string.Join(",\n", matJsons) + "\n  ],\n");
			sb.Append("  \"textures\": [\n" + string.Join(",\n", texJsons) + "\n  ],\n");
			sb.Append("  \"skeletons\": [\n" + string.Join(",\n", skelJsons) + "\n  ]\n");
			sb.Append("}\n");

			string manPath = Path.Combine(outDir, "pack.json");
			File.WriteAllText(manPath, sb.ToString(), new UTF8Encoding(false));

			Console.WriteLine($"exportmod {Path.GetFileName(packPath)} -> {outDir}");
			Console.WriteLine($"  网格 {meshOk} 个 metamesh / {subTotal} 子网格, " +
							  $"{vertTotal} 顶点, {triTotal} 三角 (lod={lastLodUsed})");
			Console.WriteLine($"  材质 {matJsons.Count}, 贴图 {texJsons.Count} ({texBytes / 1024.0 / 1024.0:F1} MB 像素)");
			if (skippedNoStream > 0)
				Console.WriteLine($"  ! 跳过 {skippedNoStream} 个没有顶点流的子网格");
			if (skippedNoLod > 0)
				Console.WriteLine($"  ! 跳过 {skippedNoLod} 个没有目标 lod 的 metamesh");
			Console.WriteLine($"  清单 {manPath}");
			return 0;
		}

		// ---------------- helpers ----------------

		/// <summary>AssetDependence.Name 是 private，只能靠 guid 反查资产表。</summary>
		private static string MatName(Dictionary<Guid, Material> byGuid, AssetDependence<Material> dep)
		{
			if (dep == null || dep.Guid == Guid.Empty) return "";
			return byGuid.TryGetValue(dep.Guid, out var m) ? m.Name : "";
		}

		private static void WriteUtf8(BinaryWriter w, string s) => w.Write(Utf8(s));

		private static byte[] Utf8(string s)
		{
			var b = Encoding.UTF8.GetBytes(s ?? "");
			var len = new byte[4 + b.Length];
			BitConverter.GetBytes((uint)b.Length).CopyTo(len, 0);
			b.CopyTo(len, 4);
			return len;
		}

		private static byte[] Ascii36(Guid g)
		{
			var s = g.ToString("D");
			var b = Encoding.ASCII.GetBytes(s);
			var outb = new byte[4 + b.Length];
			BitConverter.GetBytes((uint)b.Length).CopyTo(outb, 0);
			b.CopyTo(outb, 4);
			return outb;
		}

		private static string F(double v) => v.ToString("R", CultureInfo.InvariantCulture);
		private static string F(float v) => v.ToString("R", CultureInfo.InvariantCulture);

		private static string StrList(IEnumerable<string> xs)
			=> xs == null ? "" : string.Join(",", xs.Select(x => "\"" + Esc(x) + "\""));

		private static string Esc(string s)
			=> s == null ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"");

		private static string Sanitize(string name)
		{
			if (string.IsNullOrEmpty(name)) return "unnamed";
			var sb = new StringBuilder(name.Length);
			foreach (char c in name)
				sb.Append(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.' ? c : '_');
			return sb.ToString();
		}

		private static string UniqueName(HashSet<string> used, string baseName)
		{
			string n = baseName;
			int i = 1;
			while (!used.Add(n)) n = baseName + "_" + (i++);
			return n;
		}
	}
}