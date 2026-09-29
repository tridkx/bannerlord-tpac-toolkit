using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text;
using TpacTool.Lib;

namespace MbTool
{
	public static class Program
	{
		public static int Main(string[] argv)
		{
			// ★ 输出里有中文，而 Windows 控制台默认 GBK(936)：不钉死 UTF-8 的话，
			//   在 bash/管道里全是乱码（工具本身没问题，只是看不见）。
			try { Console.OutputEncoding = System.Text.Encoding.UTF8; } catch { }

			if (argv.Length == 0)
			{
				Usage();
				return 1;
			}

			try
			{
				switch (argv[0])
				{
					case "list": return CmdList(argv);
					case "info": return CmdInfo(argv);
					case "find": return CmdFind(argv);
					case "guidindex": return CmdGuidIndex(argv);
					case "findguid": return CmdFindGuid(argv);
					case "metacheck": return CmdMetaCheck(argv);
					case "xxh": return CmdXxh(argv);
					case "lz4test": return CmdLz4Test(argv);
					case "mataudit": return CmdMatAudit(argv);
					case "build": return Builder.Build(argv[1]);
					case "halfcheck": HalfCheck.Run(); return 0;
					case "segcheck": return CmdSegCheck(argv);
					case "mesh": return CmdMesh(argv);
					case "skel": return CmdSkel(argv);
					case "mat": return CmdMat(argv);
					case "matall": return CmdMatAll(argv);
					case "tex": return CmdTex(argv);
					case "exportmesh": return CmdExportMesh(argv);
					case "roundtrip": return CmdRoundTrip(argv);
					case "animlist": return Anim.List(argv);
					case "cliplist": return Anim.ClipList(argv);
					case "clip": return Anim.Clip(argv);
					case "anim": return Anim.Dump(argv);
					case "skeljson": return Anim.SkelJson(argv);
					case "exportmod": return ExportMod.Run(argv);
					default:
						Usage();
						return 1;
				}
			}
			catch (Exception e)
			{
				Console.Error.WriteLine("ERROR: " + e);
				return 2;
			}
		}

		private static void Usage()
		{
			Console.WriteLine(@"mbtool - Bannerlord tpac inspection tool (built on TpacTool.Lib)

  list <tpac> [filter]                 list assets in a package
  info <tpac>                          asset count grouped by type
  find <dir> <name> [name2 ...]        find assets by name across all *.tpac under dir
  guidindex <dir> <out.tsv>            dump guid<TAB>type<TAB>name<TAB>file for all tpac under dir
  mesh <tpac> <assetName>              metamesh details (lods, submeshes, counts)
  skel <tpac> [assetName]              skeleton bones with indices
  mat <tpac> <assetName>               material details
  tex <tpac> <assetName>               texture details
  exportmesh <tpac> <name> <outPrefix> dump geometry to <outPrefix>.bin + <outPrefix>.json
  roundtrip <tpac> <out>               read then write a package (validates the writer)

  -- skeletal animation --
  animlist <animations.tpac> [filter]  list skeletal animations (name / bones / duration)
  cliplist <animation_clips.tpac> [f]  list animation clips
  clip <animation_clips.tpac> <name>   one clip's metadata (incl. its animation guid)
  anim <animations.tpac> <name|guid> [out.json] [skeletons.tpac]
                                       dump animation keyframes to JSON
  skeljson <skeletons.tpac> <name> <out.json>
                                       dump skeleton (bone names / parents / rest) to JSON

  -- whole-mod export (for the offline previewer) --
  exportmod <pack.tpac> <outDir> [lod] export meshes + materials + textures(PNG)
                                       as a self-contained folder
");
		}

		private static AssetPackage Open(string path, bool data = false)
		{
			return new AssetPackage(path, true, data);
		}

		private static string TypeName(Guid g)
		{
			if (g == Metamesh.TYPE_GUID) return "Metamesh";
			if (g == Material.TYPE_GUID) return "Material";
			if (g == Texture.TYPE_GUID) return "Texture";
			if (g == Skeleton.TYPE_GUID) return "Skeleton";
			if (g == Shader.TYPE_GUID) return "Shader";
			if (g == Geometry.TYPE_GUID) return "Geometry";
			if (g == PhysicsShape.TYPE_GUID) return "PhysicsShape";
			if (g == Particle.TYPE_GUID) return "Particle";
			if (g == MorphAnimation.TYPE_GUID) return "MorphAnimation";
			if (g == SkeletalAnimation.TYPE_GUID) return "SkeletalAnimation";
			if (g == AnimationClip.TYPE_GUID) return "AnimationClip";
			if (g == ProceduralVectorField.TYPE_GUID) return "VectorField";
			return "{" + g + "}";
		}

		private static int CmdList(string[] a)
		{
			if (a.Length < 2) { Usage(); return 1; }
			string filter = a.Length > 2 ? a[2] : null;
			var pkg = Open(a[1]);
			Console.WriteLine($"# {a[1]}  guid={pkg.Guid}  version-pack={pkg.Items.Count} assets");
			foreach (var it in pkg.Items)
			{
				if (filter != null && it.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				Console.WriteLine($"{TypeName(it.Type),-18} {it.Name,-52} {it.Guid} segs={it.TypelessDataSegments.Count} v{it.Version}");
			}
			return 0;
		}

		private static int CmdInfo(string[] a)
		{
			var pkg = Open(a[1]);
			Console.WriteLine($"{a[1]}: {pkg.Items.Count} assets, package guid {pkg.Guid}");
			foreach (var g in pkg.Items.GroupBy(i => TypeName(i.Type)).OrderByDescending(g => g.Count()))
				Console.WriteLine($"  {g.Key,-18} {g.Count()}");
			return 0;
		}

		private static IEnumerable<string> Tpacs(string dir)
		{
			return Directory.EnumerateFiles(dir, "*.tpac", SearchOption.AllDirectories);
		}

		private static int CmdFind(string[] a)
		{
			if (a.Length < 3) { Usage(); return 1; }
			var wanted = a.Skip(2).ToArray();
			foreach (var file in Tpacs(a[1]))
			{
				AssetPackage pkg = null;
				try { pkg = Open(file); } catch { continue; }
				foreach (var it in pkg.Items)
				{
					foreach (var w in wanted)
					{
						if (string.Equals(it.Name, w, StringComparison.OrdinalIgnoreCase))
							Console.WriteLine($"{TypeName(it.Type),-14} {it.Name,-40} {file}");
					}
				}
			}
			return 0;
		}

		private static int CmdGuidIndex(string[] a)
		{
			var outPath = a[2];
			using var w = new StreamWriter(outPath, false, new UTF8Encoding(false));
			w.WriteLine("guid\ttype\tname\tfile");
			foreach (var file in Tpacs(a[1]))
			{
				AssetPackage pkg = null;
				try { pkg = Open(file); } catch { continue; }
				foreach (var it in pkg.Items)
					w.WriteLine($"{it.Guid}\t{TypeName(it.Type)}\t{it.Name}\t{file}");
			}
			Console.WriteLine("wrote " + outPath);
			return 0;
		}

		private static int CmdMatAudit(string[] a)
		{
			var pkg = Open(a[1]);
			var mats = new HashSet<Guid>(pkg.Items.Where(i => i.Type == Material.TYPE_GUID).Select(i => i.Guid));
			var all = new HashSet<Guid>(pkg.Items.Select(i => i.Guid));
			Console.WriteLine($"{a[1]}: {mats.Count} materials, {all.Count} assets");
			int missMesh = 0, missA = 0, missB = 0, okA = 0, okB = 0, empty = 0;
			foreach (var mm in pkg.Items.OfType<Metamesh>())
			{
				bool mmOk = mm.Material == Guid.Empty || mats.Contains(mm.Material);
				if (!mmOk) missMesh++;
				var parts = new List<string>();
				foreach (var m in mm.Meshes)
				{
					var aG = m.SecondMaterial.Guid;
					var bG = m.Material.Guid;
					if (aG != Guid.Empty) { if (mats.Contains(aG)) okA++; else missA++; }
					if (bG != Guid.Empty) { if (mats.Contains(bG)) okB++; else missB++; }
					parts.Add($"{(mats.Contains(bG) ? "M" : (bG == Guid.Empty ? "-" : "X"))}{(mats.Contains(aG) ? "S" : (aG == Guid.Empty ? "-" : "X"))}");
				}
				if (!mmOk || parts.Any(p => p.Contains('X')) || parts.All(p => p == "--"))
					Console.WriteLine($"  {mm.Name,-38} meta-mat={(mmOk ? "ok" : "MISSING")} submeshes=[{string.Join(",", parts)}] lods=[{string.Join(",", mm.Meshes.Select(x => x.Lod))}]");
				if (parts.All(p => p == "--")) empty++;
			}
			Console.WriteLine($"  metamesh-level material missing={missMesh} | submesh Material present={okB} missing={missB} | submesh SecondMaterial present={okA} missing={missA} | metameshes with no material at all={empty}");
			return 0;
		}

		private static int CmdLz4Test(string[] a)
		{
			var data = File.ReadAllBytes(a[1]);
			var enc = LZ4.LZ4Codec.EncodeHC(data, 0, data.Length);
			File.WriteAllBytes(a[2], enc);
			Console.WriteLine($"in={data.Length} lz4={enc.Length} ratio={(double)enc.Length / data.Length:F4}");
			var back = LZ4.LZ4Codec.Decode(enc, 0, enc.Length, data.Length);
			Console.WriteLine("self-decode match: " + (back.Length == data.Length && back.AsSpan().SequenceEqual(data)));
			return 0;
		}

		/// <summary>Force-loads a mesh's data segments, re-serialises them with the
		/// writer and compares the result against the bytes actually in the file.</summary>
		private static int CmdSegCheck(string[] a)
		{
			var pkg = new AssetPackage(a[1], true, true);
			var item = pkg.Items.FirstOrDefault(x => x.Name == a[2]);
			if (item == null) { Console.WriteLine("asset not found: " + a[2]); return 1; }
			Console.WriteLine($"{item.Name}: {item.TypelessDataSegments.Count} segments");
			foreach (var seg in item.TypelessDataSegments)
			{
				var raw = File.ReadAllBytes(a[1]);
				var stored = new byte[seg.StorageSize];
				Array.Copy(raw, (int) seg.Offset, stored, 0, stored.Length);
				byte[] original = seg.Format == AbstractExternalLoader.StorageFormat.LZ4HC
					? LZ4.LZ4Codec.Decode(stored, 0, stored.Length, (int) seg.ActualSize)
					: stored;

				byte[] rewritten = null;
				string kind = seg.GetType().Name;
				try
				{
					using (var ms = new MemoryStream())
					{
						using (var w = new BinaryWriter(ms))
						{
							var d = seg.GetType().GetProperty("Data").GetValue(seg);
							var wd = d.GetType().GetMethod("WriteData");
							wd.Invoke(d, new object[] { w, seg.UserData });
						}
						rewritten = ms.ToArray();
					}
				}
				catch (Exception e) { Console.WriteLine($"   {kind}: serializer failed: {e.InnerException?.Message ?? e.Message}"); continue; }

				string verdict;
				if (rewritten.Length != original.Length)
					verdict = $"LENGTH DIFFERS  original={original.Length} rewritten={rewritten.Length}";
				else
				{
					int first = -1;
					for (int i = 0; i < original.Length; i++) if (original[i] != rewritten[i]) { first = i; break; }
					verdict = first < 0 ? "identical" : $"first diff at byte {first}";
					if (first >= 0)
					{
						int n = Math.Min(24, original.Length - first);
						verdict += $"\n        original : {BitConverter.ToString(original, first, n)}\n        rewritten: {BitConverter.ToString(rewritten, first, n)}";
					}
				}
				Console.WriteLine($"   {kind,-42} actual={seg.ActualSize,9} fmt={seg.Format,-12} {verdict}");
			}
			return 0;
		}

		private static int CmdXxh(string[] a)
		{
			var hex = string.Concat(a.Skip(1));
			var bytes = new byte[hex.Length / 2];
			for (int i = 0; i < bytes.Length; i++)
				bytes[i] = Convert.ToByte(hex.Substring(i * 2, 2), 16);
			Console.WriteLine($"{XxHash64.Hash(bytes):x16}");
			return 0;
		}

		private static int CmdMetaCheck(string[] a)
		{
			var pkg = Open(a[1]);
			int ok = 0, metaOk = 0, metaDiff = 0, chkDiff = 0, noserial = 0;
			foreach (var it in pkg.Items)
			{
				if (it.RawMetadata == null) { continue; }
				var expected = XxHash64.HashMetadata(it.RawMetadata);
				if (expected != (ulong) it.MetadataChecksum)
				{
					chkDiff++;
					Console.WriteLine($"  CHECKSUM-DIFF {it.Name} ({TypeName(it.Type)}) file={it.MetadataChecksum:x16} calc={expected:x16}");
				}
				else ok++;

				byte[] rewritten;
				try { rewritten = it.WriteMetadata(); }
				catch (Exception e) { noserial++; Console.WriteLine($"  NO-SERIALIZER {it.Name} ({TypeName(it.Type)}): {e.GetType().Name}"); continue; }
				if (rewritten == null) { noserial++; continue; }
				if (rewritten.Length != it.RawMetadata.Length)
				{
					metaDiff++;
					Console.WriteLine($"  META-LEN {it.Name} ({TypeName(it.Type)}): file={it.RawMetadata.Length} written={rewritten.Length}");
					continue;
				}
				int firstDiff = -1;
				for (int i = 0; i < rewritten.Length; i++)
					if (rewritten[i] != it.RawMetadata[i]) { firstDiff = i; break; }
				if (firstDiff < 0)
				{
					metaOk++;
				}
				else
				{
					metaDiff++;
					var n = Math.Min(16, rewritten.Length - firstDiff);
					Console.WriteLine($"  META-DIFF {it.Name} ({TypeName(it.Type)}) at {firstDiff}: file={BitConverter.ToString(it.RawMetadata, firstDiff, n)} written={BitConverter.ToString(rewritten, firstDiff, n)}");
				}
			}
			Console.WriteLine($"{a[1]}: {pkg.Items.Count} assets | checksum ok={ok} bad={chkDiff} | metadata identical={metaOk} differ={metaDiff} noSerializer={noserial}");
			return 0;
		}

		private static int CmdFindGuid(string[] a)
		{
			if (a.Length < 3) { Usage(); return 1; }
			var wanted = a.Skip(2).Select(x => Guid.Parse(x)).ToHashSet();
			foreach (var file in Tpacs(a[1]))
			{
				AssetPackage pkg = null;
				try { pkg = Open(file); } catch { continue; }
				foreach (var it in pkg.Items)
				{
					if (wanted.Contains(it.Guid) || wanted.Contains(it.Type))
						Console.WriteLine($"{TypeName(it.Type),-14} {it.Name,-44} {it.Guid} {file}");
				}
			}
			return 0;
		}

		private static int CmdMesh(string[] a)
		{
			var pkg = Open(a[1], true);
			var mm = pkg.Items.OfType<Metamesh>().FirstOrDefault(m => m.Name == a[2]);
			if (mm == null)
			{
				Console.WriteLine("metamesh not found: " + a[2]);
				foreach (var m in pkg.Items.OfType<Metamesh>().Where(m => m.Name.IndexOf(a[2], StringComparison.OrdinalIgnoreCase) >= 0).Take(20))
					Console.WriteLine("  candidate: " + m.Name);
				return 1;
			}

			Console.WriteLine($"Metamesh '{mm.Name}'  guid={mm.Guid}  version={mm.Version}");
			Console.WriteLine($"  Material(guid)      = {mm.Material}");
			Console.WriteLine($"  UnknownFloat        = {mm.UnknownFloat}");
			Console.WriteLine($"  UnknownString(body) = '{mm.UnknownString}'");
			Console.WriteLine($"  ClothMetamesh       = {mm.ClothMetamesh}");
			Console.WriteLine($"  ClothUint/ClothStr  = {mm.ClothUint} '{mm.ClothString}'");
			Console.WriteLine($"  Original            = {mm.Original}");
			Console.WriteLine($"  Variations          = {mm.Variations.Count}");
			Console.WriteLine($"  EditmodeMisc        = {(mm.EditmodeMisc != null)}");
			Console.WriteLine($"  Submeshes (lods)    = {mm.Meshes.Count}");

			foreach (var m in mm.Meshes)
			{
				var vs = m.VertexStream?.Data;
				Console.WriteLine($"  --- mesh '{m.Name}' guid={m.Guid} lod={m.Lod} complete={m.IsCompleteMesh}");
				Console.WriteLine($"      mat={m.Material.Guid} second={m.SecondMaterial.Guid}");
				Console.WriteLine($"      flags=[{string.Join(",", m.Flags)}] matFlags=[{string.Join(",", m.MaterialFlags)}]");
				Console.WriteLine($"      vtx={m.VertexCount} pos={m.PositionCount} faces={m.FaceCount} vkeys={m.VertexKeyCount} skinDataSize={m.SkinDataSize} bonesUsed={m.UnknownInt2}");
				Console.WriteLine($"      bbox min={m.BoundingBox.Min} max={m.BoundingBox.Max}");
				Console.WriteLine($"      misc: u1={m.UnknownUint1} u2={m.UnknownUInt2} f1={m.UnknownFloat1} i3={m.UnknownInt3} b1={m.UnknownBool1} b2={m.UnknownBool2} b3={m.UnknownBool3}");
				Console.WriteLine($"      factorColor={m.FactorColor} factor2={m.Factor2Color} varg={m.VectorArgument} varg2={m.VectorArgument2}");
				Console.WriteLine($"      editData={(m.EditData != null)} vertexStream={(vs != null)}");
				if (vs != null)
				{
					Console.WriteLine($"      data: idx={vs.Indices.Length} pos={vs.Positions.Length} nrm={vs.Normals.Length} tan={vs.Tangents.Length} uv1={vs.Uv1.Length} uv2={vs.Uv2.Length} c1={vs.Colors1.Length} c2={vs.Colors2.Length} bw={vs.BoneWeights.Length} bi={vs.BoneIndices.Length} cnrm={vs.CompressedNormals.Length} cpos={vs.CompressedPositions.Length} ctan={vs.CompressedTangents.Length} qtan={(vs.TangentTransform?.Length ?? -1)}");
					if (vs.BoneIndices.Length > 0)
					{
						var used = new SortedSet<int>();
						foreach (var bi in vs.BoneIndices) { used.Add(bi.B1); used.Add(bi.B2); used.Add(bi.B3); used.Add(bi.B4); }
						Console.WriteLine($"      bones referenced: {used.Count} -> [{string.Join(",", used.Take(40))}{(used.Count > 40 ? ",..." : "")}]");
					}
				}
			}
			return 0;
		}

		private static int CmdSkel(string[] a)
		{
			var pkg = Open(a[1], true);
			var skeletons = pkg.Items.OfType<Skeleton>().ToList();
			if (skeletons.Count == 0) { Console.WriteLine("no skeleton in this package"); return 1; }
			foreach (var s in skeletons)
			{
				if (a.Length > 2 && s.Name != a[2]) continue;
				Console.WriteLine($"Skeleton '{s.Name}' guid={s.Guid} geometry={s.GeometryGuid}");
				var d = s.Definition?.Data;
				if (d == null) { Console.WriteLine("  (no definition data)"); continue; }
				Console.WriteLine($"  defName='{d.Name}' bones={d.Bones.Count}");
				var parents = d.CreateParentLookup();
				for (int i = 0; i < d.Bones.Count; i++)
				{
					var b = d.Bones[i];
					var t = b.RestFrame.Translation;
					Console.WriteLine($"  [{i,3}] {b.Name,-40} parent={parents[i],3} rest=({t.X:F4},{t.Y:F4},{t.Z:F4})");
				}
			}
			return 0;
		}

		private static int CmdMat(string[] a)
		{
			var pkg = Open(a[1], true);
			var m = pkg.Items.OfType<Material>().FirstOrDefault(x => x.Name == a[2]);
			if (m == null) { Console.WriteLine("material not found: " + a[2]); return 1; }
			Console.WriteLine($"Material '{m.Name}' guid={m.Guid} version={m.Version}");
			Console.WriteLine($"  billboard={m.BillboardGuid} u1={m.UnknownUint1} u2={m.UnknownUint2}");
			Console.WriteLine($"  flags=[{string.Join(",", m.Flags)}]");
			Console.WriteLine($"  vertexLayoutFlags=[{string.Join(",", m.VertexLayoutFlags)}]");
			Console.WriteLine($"  blendMode={m.BlendMode}");
			Console.WriteLine($"  shader={m.Shader.Guid}");
			Console.WriteLine($"  alphaTest={m.AlphaTest}");
			Console.WriteLine($"  shaderMatFlags=[{string.Join(",", m.ShaderMaterialFlags)}]");
			Console.WriteLine($"  textures={m.Textures.Count}");
			foreach (var kv in m.Textures)
				Console.WriteLine($"    [{kv.Key,3}] {kv.Value.Guid}");
			var e = m.ExtraMaterialSettings;
			if (e != null)
			{
				Console.WriteLine($"  extra: areaScale={e.AreamapScale} areaAmt={e.AreamapAmount} detailNrm={e.DetailnormalScale} nrmPower={e.NormalmapPower}");
				Console.WriteLine($"         mva={e.MeshVectorArgument} mva2={e.MeshVectorArgument2} fcm={e.MeshFactorColorMultiplier} f2cm={e.MeshFactor2ColorMultiplier}");
				Console.WriteLine($"         renderOrder={e.RenderOrder} mipBias={e.MipmapBias} spec={e.SpecularCoef} gloss={e.GlossCoef} parallax={e.ParallaxAmount}/{e.ParallaxOffset} ao={e.AmbientOcclusionCoef} exp={e.ExposureCompensation}");
			}
			return 0;
		}

		/// <summary>一次性列出包内所有材质的渲染状态参数（找"透明材质长什么样"用）</summary>
		private static int CmdMatAll(string[] a)
		{
			var pkg = Open(a[1], true);
			foreach (var m in pkg.Items.OfType<Material>())
			{
				var e = m.ExtraMaterialSettings;
				Console.WriteLine($"{m.Name}\t{m.BlendMode}\talphaTest={m.AlphaTest:0.####}\t" +
					$"flags=[{string.Join(",", m.Flags)}]\tlayer=[{string.Join(",", m.VertexLayoutFlags)}]\t" +
					$"shaderFlags=[{string.Join(",", m.ShaderMaterialFlags)}]\trenderOrder={(e?.RenderOrder.ToString() ?? "-")}\t" +
					$"fcm={e?.MeshFactorColorMultiplier}\tshader={m.Shader.Guid}");
			}
			return 0;
		}

		private static int CmdTex(string[] a)
		{
			var pkg = Open(a[1], true);
			var t = pkg.Items.OfType<Texture>().FirstOrDefault(x => x.Name == a[2]);
			if (t == null) { Console.WriteLine("texture not found: " + a[2]); return 1; }
			Console.WriteLine($"Texture '{t.Name}' guid={t.Guid} version={t.Version}");
			Console.WriteLine($"  source='{t.Source}'");
			Console.WriteLine($"  {t.Width}x{t.Height} mips={t.MipmapCount} array={t.ArrayCount} format={t.Format}");
			Console.WriteLine($"  flags=[{string.Join(",", t.Flags ?? new List<string>())}] systemFlags=[{string.Join(",", t.SystemFlags ?? new List<string>())}]");
			Console.WriteLine($"  billboardMat={t.BillboardMaterial?.Guid} unknownByte={t.UnknownByte} u3={t.UnknownUint3} u4={t.UnknownUint4} u5={t.UnknownUint5} u6={t.UnknownUint6} u7={t.UnknownUint7} ulong={t.UnknownUlong} ulong2={t.UnknownUlong2} bool={t.UnknownBool}");
			Console.WriteLine($"  generated={t.GeneratedAssets?.Count ?? 0} pixels={(t.TexturePixels != null)}");
			if (t.TexturePixels != null)
			{
				var pix = t.TexturePixels.Data;
				Console.WriteLine($"  pixeldata primary len={pix?.PrimaryRawImage?.Length ?? -1} arrays={pix?.RawImage?.Length ?? -1}");
			}
			return 0;
		}

		private static int CmdExportMesh(string[] a)
		{
			var pkg = Open(a[1], true);
			var mm = pkg.Items.OfType<Metamesh>().FirstOrDefault(x => x.Name == a[2]);
			if (mm == null) { Console.WriteLine("metamesh not found: " + a[2]); return 1; }

			var sub = mm.Meshes.OrderBy(x => x.Lod).First();
			var vs = sub.VertexStream?.Data;
			if (vs == null) { Console.WriteLine("no vertex stream"); return 1; }

			var binPath = a[3] + ".bin";
			var jsonPath = a[3] + ".json";

			using (var fs = File.Create(binPath))
			using (var w = new BinaryWriter(fs))
			{
				int n = vs.Positions.Length;
				w.Write(0x4556424D); // 'MBVE'
				w.Write(n);
				w.Write(vs.Indices.Length);
				w.Write(vs.BoneIndices.Length);
				w.Write(vs.Normals.Length);
				w.Write(vs.Tangents.Length);
				w.Write(vs.Uv1.Length);
				w.Write(vs.Uv2.Length);
				w.Write(vs.Colors1.Length);
				w.Write(vs.CompressedNormals.Length);
				w.Write(vs.CompressedPositions.Length);
				w.Write(vs.CompressedTangents.Length);
				w.Write(vs.TangentTransform?.Length ?? -1);
				w.Write(vs.UnknownAnotherPositions?.Length ?? -1);

				foreach (var p in vs.Positions) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); }
				foreach (var p in vs.Normals) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); }
				foreach (var p in vs.Tangents) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); w.Write(p.W); }
				foreach (var p in vs.Uv1) { w.Write(p.X); w.Write(p.Y); }
				foreach (var p in vs.Uv2) { w.Write(p.X); w.Write(p.Y); }
				foreach (var p in vs.Colors1) { w.Write(p.R); w.Write(p.G); w.Write(p.B); w.Write(p.A); }
				foreach (var p in vs.BoneIndices) { w.Write(p.B1); w.Write(p.B2); w.Write(p.B3); w.Write(p.B4); }
				foreach (var p in vs.BoneWeights) { w.Write(p.W1); w.Write(p.W2); w.Write(p.W3); w.Write(p.W4); }
				foreach (var p in vs.Indices) w.Write(p);
				// extra arrays appended after the indices (order fixed by this tool)
				int qn = vs.TangentTransform?.Length ?? -1;
				w.Write(qn);
				if (qn > 0)
					foreach (var q in vs.TangentTransform) { w.Write(q.RawX); w.Write(q.RawY); w.Write(q.RawZ); w.Write(q.RawW); }
				foreach (var p in vs.CompressedNormals) w.Write(p.RawData);
				foreach (var p in vs.CompressedPositions) { w.Write(SystemHalf.Half.GetBits(p.X)); w.Write(SystemHalf.Half.GetBits(p.Y)); w.Write(SystemHalf.Half.GetBits(p.Z)); w.Write(SystemHalf.Half.GetBits(p.W)); }
				foreach (var p in vs.CompressedTangents) w.Write(p.RawData);
				int anp = vs.UnknownAnotherPositions?.Length ?? -1;
				w.Write(anp);
				if (anp > 0)
					foreach (var p in vs.UnknownAnotherPositions) { w.Write(p.X); w.Write(p.Y); w.Write(p.Z); }
			}

			using (var w = new StreamWriter(jsonPath, false, new UTF8Encoding(false)))
			{
				w.WriteLine("{");
				w.WriteLine($"  \"name\": \"{Esc(mm.Name)}\",");
				w.WriteLine($"  \"guid\": \"{mm.Guid}\",");
				w.WriteLine($"  \"bodyPart\": \"{Esc(mm.UnknownString)}\",");
				w.WriteLine($"  \"submesh\": \"{Esc(sub.Name)}\",");
				w.WriteLine($"  \"lod\": {sub.Lod},");
				w.WriteLine($"  \"materialGuid\": \"{sub.Material.Guid}\",");
				w.WriteLine($"  \"secondMaterialGuid\": \"{sub.SecondMaterial.Guid}\",");
				w.WriteLine($"  \"vertexCount\": {vs.Positions.Length},");
				w.WriteLine($"  \"indexCount\": {vs.Indices.Length},");
				w.WriteLine($"  \"bboxMin\": [{sub.BoundingBox.Min.X:R},{sub.BoundingBox.Min.Y:R},{sub.BoundingBox.Min.Z:R}],");
				w.WriteLine($"  \"bboxMax\": [{sub.BoundingBox.Max.X:R},{sub.BoundingBox.Max.Y:R},{sub.BoundingBox.Max.Z:R}],");
				w.WriteLine($"  \"flags\": [{string.Join(",", sub.Flags.Select(f => "\"" + Esc(f) + "\""))}],");
				w.WriteLine($"  \"materialFlags\": [{string.Join(",", sub.MaterialFlags.Select(f => "\"" + Esc(f) + "\""))}],");
				w.WriteLine($"  \"submeshCount\": {mm.Meshes.Count},");
				w.WriteLine($"  \"lods\": [{string.Join(",", mm.Meshes.Select(m => m.Lod))}]");
				w.WriteLine("}");
			}

			Console.WriteLine($"exported {mm.Name} lod{sub.Lod}: {vs.Positions.Length} verts, {vs.Indices.Length} indices -> {binPath}");
			return 0;
		}

		private static string Esc(string s) => s == null ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"");

		private static int CmdRoundTrip(string[] a)
		{
			bool force = a.Length > 3 && a[3] == "force";
			var pkg = Open(a[1], force);
			// when not forcing, every segment is copied verbatim from the source file
			int loaded = 0;
			if (force)
			{
				foreach (var it in pkg.Items)
				{
					foreach (var seg in it.TypelessDataSegments)
					{
						try { seg.MarkLongLive(); loaded++; } catch { }
					}
				}
			}
			pkg.Save(a[2]);
			Console.WriteLine($"round-tripped {a[1]} -> {a[2]}  ({pkg.Items.Count} assets, {loaded} segments force-loaded)");
			var fi = new FileInfo(a[1]);
			var fo = new FileInfo(a[2]);
			Console.WriteLine($"  original {fi.Length} bytes, rewritten {fo.Length} bytes");
			return 0;
		}
	}
}
