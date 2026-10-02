// Builds a Bannerlord asset package (pack0.tpac) for a custom character.
//
// Strategy: every asset type is *cloned from a vanilla template* so that fields whose
// meaning is not fully understood keep engine-valid values, and only the data we
// author (geometry buffers, texture pixels, material bindings, names and GUIDs) is
// replaced.  All structures were validated against 585 vanilla / editor-made assets
// (metadata round-trips byte-identically, per-asset and per-segment checksums match).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text.Json;
using TpacTool.Lib;

namespace MbTool
{
	public static class Builder
	{
		private class Ctx
		{
			public AssetPackage Package;
			public Dictionary<string, AssetPackage> OpenPackages = new Dictionary<string, AssetPackage>();
			public List<string> Log = new List<string>();
			// ★ 种子不能写死。原先固定为 20260910，导致**同一工具构建的每个 mod 都得到
			//   完全相同的 GUID 序列** —— 两个 mod 同时加载时，引擎按 GUID 索引资产，
			//   后加载的把先加载的覆盖掉，表现为"贴图紊乱"（实测 AdaWongCheongsam 与
			//   ValerieHarmonRB 有 31 个 GUID 完全撞车）。
			//   改为由包 GUID 派生：同一个 spec 仍然可复现，不同包之间必然不同。
			public Random Rng = new Random(20260910);

			public void SeedRng(Guid packageGuid)
			{
				var pb = packageGuid.ToByteArray();
				int seed = BitConverter.ToInt32(pb, 0) ^ BitConverter.ToInt32(pb, 4)
				           ^ BitConverter.ToInt32(pb, 8) ^ BitConverter.ToInt32(pb, 12)
				           ^ 20260910;
				Rng = new Random(seed);
			}
			public JsonElement Spec;

			public AssetPackage Pkg(string path)
			{
				if (!OpenPackages.TryGetValue(path, out var p))
				{
					p = new AssetPackage(path, true, true);
					OpenPackages[path] = p;
				}
				return p;
			}

			private readonly Dictionary<string, AssetItem> _tmplCache = new Dictionary<string, AssetItem>();

			/// <summary>Fetch a named template asset by its key in spec.templates.</summary>
			public T Template<T>(string key) where T : AssetItem
			{
				if (_tmplCache.TryGetValue(key, out var cached))
					return (T) cached;
				var t = Spec.GetProperty("templates").GetProperty(key);
				var path = t.GetProperty("tpac").GetString();
				var name = t.GetProperty("name").GetString();
				var item = Pkg(path).Items.OfType<T>().FirstOrDefault(x => x.Name == name);
				if (item == null)
					throw new Exception($"template '{key}' ({name}) not found in {path}");
				_tmplCache[key] = item;
				return item;
			}

			public Guid NewGuid()
			{
				var b = new byte[16];
				Rng.NextBytes(b);
				return new Guid(b);
			}
		}

		public static int Build(string specPath)
		{
			var ctx = new Ctx();
			ctx.Spec = JsonDocument.Parse(File.ReadAllText(specPath)).RootElement;
			var spec = ctx.Spec;

			string output = spec.GetProperty("output").GetString();
			var guidStr = spec.TryGetProperty("packageGuid", out var g) ? g.GetString() : null;
			var pkgGuid = string.IsNullOrEmpty(guidStr) ? Guid.NewGuid() : Guid.Parse(guidStr);
			ctx.Package = new AssetPackage(pkgGuid);
			ctx.SeedRng(pkgGuid);   // ★ 先定包 GUID，再据它派生资产 GUID 序列

			var texByName = new Dictionary<string, Texture>();
			if (spec.TryGetProperty("textures", out var texs))
			{
				foreach (var t in texs.EnumerateArray())
				{
					var tex = BuildTexture(ctx, t);
					texByName[tex.Name] = tex;
					ctx.Package.Items.Add(tex);
					ctx.Log.Add($"  texture  {tex.Name,-32} {tex.Width}x{tex.Height} {tex.Format} mips={tex.MipmapCount} " +
								$"blob={tex.TexturePixels.Data.RawImage[0].Sum(x => (long) x.Length) / 1024} KB");
				}
			}

			var matByName = new Dictionary<string, Material>();
			if (spec.TryGetProperty("materials", out var mats))
			{
				foreach (var m in mats.EnumerateArray())
				{
					var mat = BuildMaterial(ctx, m, texByName);
					matByName[mat.Name] = mat;
					ctx.Package.Items.Add(mat);
					ctx.Log.Add($"  material {mat.Name,-32} blend={mat.BlendMode} flags=[{string.Join(",", mat.Flags)}] " +
								$"layout=[{string.Join(",", mat.VertexLayoutFlags)}] tex={mat.Textures.Count}");
				}
			}

			// 骨架先于网格：新增种族要用自定义骨架（action_sets.xml 按 skeleton 名引用）
			if (spec.TryGetProperty("skeletons", out var skels))
			{
				foreach (var s in skels.EnumerateArray())
				{
					var sk = BuildSkeleton(ctx, s);
					ctx.Package.Items.Add(sk);
					ctx.Log.Add($"  skeleton {sk.Name,-31} bones={sk.Definition.Data.Bones.Count} " +
								$"metaVersion={sk.MetaVersion} geom={sk.GeometryGuid}");
				}
			}

			if (spec.TryGetProperty("meshes", out var meshes))
			{
				foreach (var m in meshes.EnumerateArray())
				{
					var mm = BuildMetamesh(ctx, m, matByName);
					ctx.Package.Items.Add(mm);
					ctx.Log.Add($"  metamesh {mm.Name,-31} submeshes={mm.Meshes.Count} " +
								$"verts={mm.Meshes.Sum(x => x.VertexCount)} tris={mm.Meshes.Sum(x => x.FaceCount)} " +
								$"bodyPart='{mm.UnknownString}'");
				}
			}

			var dir = Path.GetDirectoryName(Path.GetFullPath(output));
			if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
			ctx.Package.Save(output);
			Console.WriteLine($"wrote {output} ({new FileInfo(output).Length / 1048576.0:F1} MB, {ctx.Package.Items.Count} assets)");
			foreach (var l in ctx.Log) Console.WriteLine(l);
			return 0;
		}

		// ---------------------------------------------------------------- skeleton
		/// <summary>
		/// 构造骨架资产。★ 与 mesh / material 同一策略：从原版模板克隆，保住
		/// MetaVersion / GeometryGuid / **骨轴朝向** 这些"语义未完全弄清"的字段，
		/// 只替换我们真正要改的数据 —— 这里是每根骨的 RestFrame。
		///
		/// RestFrame 是**局部矩阵**（行主序 16 个 float，行向量约定
		/// W_child = L_child * W_parent）。矩阵由 Python 侧算好写进 spec，
		/// C# 侧只做填充 —— 便于用 numpy 审计，也让这里保持无逻辑。
		///
		/// 引擎按**名字**索引骨架（Skeleton.GetBoneIndexFromName），因此
		/// 资产名 Name 与定义名 Definition.Data.Name 必须一致。
		/// </summary>
		private static Skeleton BuildSkeleton(Ctx ctx, JsonElement spec)
		{
			var tmpl = ctx.Template<Skeleton>(spec.GetProperty("template").GetString());
			var sk = (Skeleton) tmpl.Clone();
			sk.Name = spec.GetProperty("name").GetString();
			sk.Guid = ctx.NewGuid();
			// ★ TpacTool 的 Skeleton.Clone() 漏拷 MetaVersion（会留 0 = 版本不符）
			sk.MetaVersion = tmpl.MetaVersion;

			if (sk.Definition?.Data == null)
				throw new Exception($"skeleton template '{tmpl.Name}' 没有 Definition 数据段");
			var def = sk.Definition.Data;
			def.Name = sk.Name;

			var bonesSpec = spec.GetProperty("bones").EnumerateArray().ToArray();
			var nodes = new List<BoneNode>(bonesSpec.Length);
			foreach (var b in bonesSpec)
			{
				var a = b.GetProperty("rest").EnumerateArray().Select(x => x.GetSingle()).ToArray();
				if (a.Length != 16)
					throw new Exception($"skeleton '{sk.Name}': bone '{b.GetProperty("name").GetString()}' " +
										$"的 rest 需要 16 个元素，实得 {a.Length}");
				nodes.Add(new BoneNode
				{
					Name = b.GetProperty("name").GetString(),
					RestFrame = new Matrix4x4(a[0], a[1], a[2], a[3],
											  a[4], a[5], a[6], a[7],
											  a[8], a[9], a[10], a[11],
											  a[12], a[13], a[14], a[15]),
				});
			}
			for (int i = 0; i < nodes.Count; i++)
			{
				int p = bonesSpec[i].GetProperty("parent").GetInt32();
				if (p < 0)
					continue;
				if (p >= nodes.Count)
					throw new Exception($"skeleton '{sk.Name}': bone[{i}] parent={p} 越界");
				if (p >= i)
					throw new Exception($"skeleton '{sk.Name}': bone[{i}] parent={p} 违反拓扑序（父必须在子之前）");
				nodes[i].Parent = nodes[p];
			}
			def.Bones.Clear();
			def.Bones.AddRange(nodes);

			// ★ 数据段必须走 ConsumeDataSegments 注册进 TypelessDataSegments。
			//   TpacTool 的 Skeleton.Clone() 只给 Definition 属性赋了值（auto-property），
			//   并没有把它登记到段列表 —— 只靠 Clone 保存会写出 segs=0，
			//   `mbtool skel` 回读是 "(no definition data)"，骨架数据整个丢失。
			//   loader 自身字段（OwnerGuid / UnknownUint / UnknownUlong / UserData）
			//   也要从模板拷，否则段的描述不完整。
			var segs = new List<AbstractExternalLoader>();
			var ld = new ExternalLoader<SkeletonDefinitionData>(def);
			ld.OwnerGuid = sk.Guid;
			ld.UnknownUint = tmpl.Definition.UnknownUint;
			ld.UnknownUlong = tmpl.Definition.UnknownUlong;
			foreach (var kv in tmpl.Definition.UserData)
				ld.UserData[kv.Key] = kv.Value;
			segs.Add(ld);

			if (tmpl.UserData?.Data != null)
			{
				var ud = new ExternalLoader<SkeletonUserData>(tmpl.UserData.Data);
				ud.OwnerGuid = sk.Guid;
				ud.UnknownUint = tmpl.UserData.UnknownUint;
				ud.UnknownUlong = tmpl.UserData.UnknownUlong;
				foreach (var kv in tmpl.UserData.UserData)
					ud.UserData[kv.Key] = kv.Value;
				segs.Add(ud);
			}
			sk.ConsumeDataSegments(segs.ToArray());
			return sk;
		}

		// ------------------------------------------------------------------ texture
		private static Texture BuildTexture(Ctx ctx, JsonElement spec)
		{
			var tmpl = ctx.Template<Texture>(spec.GetProperty("template").GetString());
			var tex = new Texture
			{
				Guid = ctx.NewGuid(),
				Name = spec.GetProperty("name").GetString(),
				Version = tmpl.Version,
				MetaVersion = tmpl.MetaVersion,
				BillboardMaterial = AssetDependence<Material>.CreateEmpty(),
				UnknownUint1 = tmpl.UnknownUint1,
				Source = spec.TryGetProperty("source", out var s) ? s.GetString() : "generated",
				UnknownUlong = tmpl.UnknownUlong,
				UnknownBool = tmpl.UnknownBool,
				UnknownUint2 = tmpl.UnknownUint2,
				Flags = new List<string>(tmpl.Flags ?? new List<string>()),
				UnknownUint3 = tmpl.UnknownUint3,
				UnknownByte = tmpl.UnknownByte,
				UnknownUint4 = tmpl.UnknownUint4,
				UnknownUint5 = tmpl.UnknownUint5,
				SystemFlags = new List<string>(tmpl.SystemFlags ?? new List<string>()),
				UnknownUint6 = tmpl.UnknownUint6,
				UnknownUint7 = tmpl.UnknownUint7,
				GeneratedAssets = new List<Tuple<Guid, Guid>>(),
				UnknownUlong2 = tmpl.UnknownUlong2,
				ArrayCount = 1,
				Width = (uint) spec.GetProperty("width").GetInt32(),
				Height = (uint) spec.GetProperty("height").GetInt32(),
				MipmapCount = (byte) spec.GetProperty("mips").GetInt32(),
			};
			if (!Enum.TryParse<TextureFormat>(spec.GetProperty("format").GetString(), true, out var fmt))
				throw new Exception("unknown texture format");
			tex.Format = fmt;
			if (spec.TryGetProperty("flags", out var fl))
				tex.Flags = fl.EnumerateArray().Select(x => x.GetString()).ToList();
			if (spec.TryGetProperty("systemFlags", out var sf))
				tex.SystemFlags = sf.EnumerateArray().Select(x => x.GetString()).ToList();

			// split the raw blob into per-mip arrays
			var blob = File.ReadAllBytes(spec.GetProperty("blob").GetString());
			int w = (int) tex.Width, h = (int) tex.Height;
			var mips = new byte[tex.MipmapCount][];
			int off = 0;
			for (int i = 0; i < tex.MipmapCount; i++)
			{
				int mw = Math.Max(1, w >> i), mh = Math.Max(1, h >> i);
				int size = MipSize(mw, mh, fmt);
				if (off + size > blob.Length)
					throw new Exception($"blob too small for mip {i}: need {size} at {off}, have {blob.Length}");
				mips[i] = new byte[size];
				Array.Copy(blob, off, mips[i], 0, size);
				off += size;
			}
			if (off != blob.Length)
				Console.WriteLine($"    note: texture {tex.Name} blob has {blob.Length - off} trailing bytes");

			var pix = new TexturePixelData { RawImage = new[] { mips } };
			var loader = new ExternalLoader<TexturePixelData>(pix);
			loader.UserData[TexturePixelData.KEY_WIDTH] = w;
			loader.UserData[TexturePixelData.KEY_HEIGHT] = h;
			loader.UserData[TexturePixelData.KEY_ARRAY] = 1;
			loader.UserData[TexturePixelData.KEY_MIPMAP] = (int) tex.MipmapCount;
			loader.UserData[TexturePixelData.KEY_FORMAT] = fmt;
			loader.OwnerGuid = tex.Guid;
			loader.UnknownUint = 0;
			loader.UnknownUlong = 0;
			tex.TexturePixels = loader;
			tex.ConsumeDataSegments(new AbstractExternalLoader[] { loader });
			return tex;
		}

		private static int MipSize(int w, int h, TextureFormat fmt)
		{
			switch (fmt)
			{
				case TextureFormat.DXT1:
				case TextureFormat.DXT2:
				case TextureFormat.BC4:
					return ((w + 3) / 4) * ((h + 3) / 4) * 8;
				case TextureFormat.DXT3:
				case TextureFormat.DXT4:
				case TextureFormat.DXT5:
				case TextureFormat.BC5:
				case TextureFormat.BC6H_UF16:
				case TextureFormat.BC7:
					return ((w + 3) / 4) * ((h + 3) / 4) * 16;
				case TextureFormat.R8_UNORM:
				case TextureFormat.A8_UNORM:
				case TextureFormat.L8_UNORM:
					return w * h;
				case TextureFormat.R8G8_UNORM:
					return w * h * 2;
				case TextureFormat.R8G8B8A8_UNORM:
				case TextureFormat.B8G8R8A8_UNORM:
				case TextureFormat.B8G8R8X8_UNORM:
					return w * h * 4;
				default:
					throw new Exception("unsupported texture format " + fmt);
			}
		}

		// ----------------------------------------------------------------- material
		private static Material BuildMaterial(Ctx ctx, JsonElement spec, Dictionary<string, Texture> textures)
		{
			var tmpl = ctx.Template<Material>(spec.GetProperty("template").GetString());
			var mat = new Material
			{
				Guid = ctx.NewGuid(),
				Name = spec.GetProperty("name").GetString(),
				Version = tmpl.Version,
				MetaVersion = tmpl.MetaVersion,
				SubVersion = tmpl.SubVersion,
				BillboardGuid = tmpl.BillboardGuid,
				UnknownUint1 = tmpl.UnknownUint1,
				UnknownUint2 = tmpl.UnknownUint2,
				Flags = new List<string>(tmpl.Flags),
				VertexLayoutFlags = new List<string>(tmpl.VertexLayoutFlags),
				BlendMode = tmpl.BlendMode,
				Shader = new AssetDependence<Shader>(tmpl.Shader.Guid),
				AlphaTest = tmpl.AlphaTest,
				ShaderMaterialFlags = new List<string>(tmpl.ShaderMaterialFlags),
				ExtraMaterialSettings = tmpl.ExtraMaterialSettings,
				Textures = new SortedDictionary<int, AssetDependence<Texture>>(),
			};
			if (spec.TryGetProperty("blendMode", out var bm)) mat.BlendMode = bm.GetString();
			if (spec.TryGetProperty("alphaTest", out var at)) mat.AlphaTest = at.GetSingle();
			if (spec.TryGetProperty("flags", out var fl)) mat.Flags = fl.EnumerateArray().Select(x => x.GetString()).ToList();
			if (spec.TryGetProperty("vertexLayoutFlags", out var vl))
				mat.VertexLayoutFlags = vl.EnumerateArray().Select(x => x.GetString()).ToList();
			if (spec.TryGetProperty("shaderMaterialFlags", out var smf))
				mat.ShaderMaterialFlags = smf.EnumerateArray().Select(x => x.GetString()).ToList();
			// copy the template's texture bindings, then override/extend from the spec
			foreach (var kv in tmpl.Textures)
				mat.Textures[kv.Key] = new AssetDependence<Texture>(kv.Value.Guid);

			// NOTE: 必须放在复制模板贴图**之后** —— 否则刚删掉的槽会被模板再填回来（原实现就是这个问题）
			if (spec.TryGetProperty("dropTextureSlots", out var drop))
			{
				var dropSet = drop.EnumerateArray().Select(x => x.GetInt32()).ToHashSet();
				foreach (var key in mat.Textures.Keys.Where(k => dropSet.Contains(k)).ToList())
					mat.Textures.Remove(key);
			}

			if (spec.TryGetProperty("textures", out var ts))
			{
				foreach (var p in ts.EnumerateObject())
				{
					int slot = int.Parse(p.Name);
					var texName = p.Value.GetString();
					if (texName == null)
						mat.Textures.Remove(slot);
					else if (textures.TryGetValue(texName, out var tx))
						mat.Textures[slot] = new AssetDependence<Texture>(tx.Guid);
					else
						throw new Exception($"material {mat.Name}: unknown texture {texName}");
				}
			}
			return mat;
		}

		// ------------------------------------------------------------------- mesh
		private static Metamesh BuildMetamesh(Ctx ctx, JsonElement spec, Dictionary<string, Material> materials)
		{
			var tmpl = ctx.Template<Metamesh>(spec.GetProperty("template").GetString());
			var tmplMesh = tmpl.Meshes[0];

			var mm = new Metamesh
			{
				Guid = ctx.NewGuid(),
				Name = spec.GetProperty("name").GetString(),
				Version = tmpl.Version,
				MetaVersion = tmpl.MetaVersion,
				UnknownFloat = tmpl.UnknownFloat,
				UnknownString = spec.TryGetProperty("bodyPart", out var bp) ? bp.GetString() : tmpl.UnknownString,
				ClothMetamesh = Guid.Empty,
				UnknownUint = 0,
				ClothUint = 0,
				ClothString = string.Empty,
				Original = Guid.Empty,
				Variations = new List<Guid>(),
				UnknownBool1 = true,
				UnknownBool2 = true,
				Meshes = new List<Mesh>(),
				Material = Guid.Empty,
			};

			var segments = new List<AbstractExternalLoader>();

			// EditmodeMiscData has no serializer in the library, so reuse the template's blob
			if (tmpl.EditmodeMisc != null)
			{
				var misc = new ExternalLoader<EditmodeMiscData>(tmpl.EditmodeMisc.Data);
				misc.OwnerGuid = ctx.NewGuid();
				misc.UnknownUint = 0;
				misc.UnknownUlong = 0;
				mm.EditmodeMisc = misc;
				segments.Add(misc);
			}

			// ---- test path: clone a vanilla metamesh verbatim under a new name ----
			if (spec.TryGetProperty("cloneFrom", out var cf))
			{
				var src = ctx.Template<Metamesh>(cf.GetString());
				mm.MesoCloneFrom(ctx, src);
				return mm;
			}

			var groupNames = new List<string>();
			bool first = true;
			foreach (var gspec in spec.GetProperty("groups").EnumerateArray())
			{
				var geoFull = ReadMgeo(gspec.GetProperty("geometry").GetString());
				var matName = gspec.GetProperty("material").GetString();
				if (!materials.TryGetValue(matName, out var mat))
					throw new Exception($"mesh {mm.Name}: unknown material {matName}");
				if (first) { mm.Material = mat.Guid; first = false; }

				var baseName = gspec.TryGetProperty("name", out var n) ? n.GetString()
					: (groupNames.Count == 0 ? mm.Name : mm.Name + "." + groupNames.Count);
				var parts = SplitGeo(geoFull);
				int partIdx = 0;
				foreach (var geo in parts)
				{
				var name = partIdx == 0 ? baseName : baseName + ".b" + (partIdx + 1);
				partIdx++;
				groupNames.Add(name);

				var mesh = new Mesh
				{
					Guid = ctx.NewGuid(),
					Name = name,
					IsCompleteMesh = true,
					Lod = 0,
					SubVersion = tmplMesh.SubVersion,
					UnknownUint1 = 2,
					SecondMaterial = AssetDependence<Material>.CreateEmpty(),
					Material = new AssetDependence<Material>(mat.Guid),
					UnknownUInt2 = 0,
					Flags = new List<string>(tmplMesh.Flags),
					FactorColor = Vector4.One,
					Factor2Color = Vector4.One,
					VectorArgument = Vector4.Zero,
					VectorArgument2 = Vector4.Zero,
					VertexKeyCount = 0,
					PositionCount = geo.Count,
					FaceCount = geo.Indices.Length / 3,
					VertexCount = geo.Count,
					SkinDataSize = geo.Count,
					UnknownInt2 = geo.BonesUsed,
					MaterialFlags = new List<string>(tmplMesh.MaterialFlags),
					UnknownFloat1 = 1f,
					ClothingMaterial = new ClothingMaterial(),
					UnknownInt3 = tmplMesh.UnknownInt3,
					UnknownBool1 = false,
					UnknownBool2 = false,
					UnknownBool3 = false,
				};
				if (gspec.TryGetProperty("flags", out var fl))
					mesh.Flags = fl.EnumerateArray().Select(x => x.GetString()).ToList();
				if (gspec.TryGetProperty("materialFlags", out var mf))
					mesh.MaterialFlags = mf.EnumerateArray().Select(x => x.GetString()).ToList();

				mesh.BoundingBox = new BoundingBox(geo.Min, geo.Max);

				// ---- vertex stream ----
				var vs = new VertexStreamData
				{
					Positions = geo.Positions,
					Normals = geo.Normals,
					Tangents = geo.Tangents,
					Uv1 = geo.Uv1,
					Uv2 = geo.Uv2,
					Colors1 = geo.Colors1,
					Colors2 = new AbstractMeshData.Color[geo.Count],
					BoneIndices = geo.BoneIndices,
					BoneWeights = geo.BoneWeights,
					UnknownAnotherPositions = geo.Positions,
					Indices = geo.Indices,
					CompressedNormals = new VertexStreamData.X11Y11Z10[geo.Count],
					CompressedPositions = new VertexStreamData.Half4[geo.Count],
					CompressedTangents = new VertexStreamData.X10Y11Z10W1[geo.Count],
					TangentTransform = new VertexStreamData.SnormShort4[geo.Count],
				};
				for (int i = 0; i < geo.Count; i++)
				{
					var cn = new VertexStreamData.X11Y11Z10();
					cn.X = geo.Normals[i].X; cn.Y = geo.Normals[i].Y; cn.Z = geo.Normals[i].Z;
					vs.CompressedNormals[i] = cn;

					var t = geo.Tangents[i];
					var ct = new VertexStreamData.X10Y11Z10W1();
					ct.X = t.X; ct.Y = t.Y; ct.Z = t.Z; ct.Sign = t.W < 0 ? -1 : 1;
					vs.CompressedTangents[i] = ct;

					var cp = new VertexStreamData.Half4
					{
						X = (SystemHalf.Half) geo.Positions[i].X,
						Y = (SystemHalf.Half) geo.Positions[i].Y,
						Z = (SystemHalf.Half) geo.Positions[i].Z,
						W = (SystemHalf.Half) 1f,
					};
					vs.CompressedPositions[i] = cp;

					// Q-tangent: quaternion of the rotation whose columns are (N, T, N x T).
					// Verified exactly against 16 497 vanilla vertices.
					var nrm = Vector3.Normalize(geo.Normals[i]);
					var tan = geo.Tangents[i];
					var tv = new Vector3(tan.X, tan.Y, tan.Z);
					tv -= nrm * Vector3.Dot(nrm, tv);
					if (tv.LengthSquared() < 1e-12)
						tv = Math.Abs(nrm.Z) < 0.9f ? Vector3.Normalize(Vector3.Cross(nrm, Vector3.UnitZ))
												   : Vector3.Normalize(Vector3.Cross(nrm, Vector3.UnitX));
					else tv = Vector3.Normalize(tv);
					var bin = Vector3.Cross(nrm, tv);
					vs.TangentTransform[i] = QuatFromColumns(tv, bin, nrm);
				}
				var loader = new ExternalLoader<VertexStreamData>(vs);
				loader.UserData[VertexStreamData.KEY_HAS_QTANGENT] = true;
				loader.UserData[VertexStreamData.KEY_IS_32BIT_INDEX] = geo.Count >= ushort.MaxValue;
				loader.OwnerGuid = mesh.Guid;
				loader.UnknownUint = 1;
				loader.UnknownUlong = 0;
				mesh.VertexStream = loader;

				// ---- edit data (mirrors the stream; new assets keep one position per vertex) ----
				var ed = new MeshEditData
				{
					Positions = geo.Positions.Select((p, i) => new Vector4(p, i)).ToArray(),
					UnusedVec3 = new Vector4[geo.Count],
					Vertices = new MeshEditData.Vertex[geo.Count],
					Faces = new MeshEditData.Face[geo.Indices.Length / 3],
				};
				for (int i = 0; i < geo.Count; i++)
				{
					var nv = new Vector4(geo.Normals[i], 0f);
					ed.Vertices[i] = new MeshEditData.Vertex
					{
						PositionIndex = (uint) i,
						Normal = nv,
						Tangent = new Vector4(geo.Tangents[i].X, geo.Tangents[i].Y, geo.Tangents[i].Z, 0f),
						Binormal = new Vector4(Vector3.Cross(geo.Normals[i],
							new Vector3(geo.Tangents[i].X, geo.Tangents[i].Y, geo.Tangents[i].Z)), 0f),
						Padding = nv,
						Uv = geo.Uv1[i],
						SecondUv = geo.Uv2[i],
						Color = geo.Colors1[i],
						SecondColor = geo.Colors1[i],
					};
				}
				for (int i = 0; i < ed.Faces.Length; i++)
					ed.Faces[i] = new MeshEditData.Face
					{
						V0 = (int) geo.Indices[i * 3],
						V1 = (int) geo.Indices[i * 3 + 1],
						V2 = (int) geo.Indices[i * 3 + 2],
					};
				var edLoader = new ExternalLoader<MeshEditData>(ed);
				edLoader.OwnerGuid = mesh.Guid;
				edLoader.UnknownUint = 0;
				edLoader.UnknownUlong = 0;
				mesh.EditData = edLoader;
				segments.Add(edLoader);
				segments.Add(loader);

				mm.Meshes.Add(mesh);
				}
			}

			// attaches the loaders to the submeshes and registers them as the asset's
			// data segments (this is what actually writes the geometry into the tpac)
			mm.ConsumeDataSegments(segments.ToArray());
			return mm;
		}

		/// <summary>
		/// Vanilla submeshes always stay below 65535 vertices *and* indices, which is
		/// what makes the 16/32-bit index choice unambiguous.  Large groups are split
		/// into several submeshes sharing one material.
		/// </summary>
		private static List<Geo> SplitGeo(Geo g, int maxVerts = 60000, int maxIndices = 60000)
		{
			if (g.Count < maxVerts && g.Indices.Length < maxIndices)
				return new List<Geo> { g };

			var chunks = new List<Geo>();
			var used = new HashSet<int>();
			var tris = new List<int>();
			for (int t = 0; t < g.Indices.Length; t += 3)
			{
				int a = g.Indices[t], b = g.Indices[t + 1], c = g.Indices[t + 2];
				var probe = new HashSet<int>(used) { a, b, c };
				if (tris.Count > 0 && (probe.Count > maxVerts || tris.Count + 3 > maxIndices))
				{
					chunks.Add(ExtractGeo(g, used, tris));
					used = new HashSet<int>();
					tris = new List<int>();
				}
				used.Add(a); used.Add(b); used.Add(c);
				tris.Add(a); tris.Add(b); tris.Add(c);
			}
			if (tris.Count > 0)
				chunks.Add(ExtractGeo(g, used, tris));
			return chunks;
		}

		private static Geo ExtractGeo(Geo g, HashSet<int> used, List<int> tris)
		{
			var map = new Dictionary<int, int>();
			var list = used.ToList();
			list.Sort();
			for (int i = 0; i < list.Count; i++) map[list[i]] = i;
			int n = list.Count;
			var o = new Geo { Count = n };
			o.Positions = new Vector3[n]; o.Normals = new Vector3[n]; o.Tangents = new Vector4[n];
			o.Uv1 = new Vector2[n]; o.Uv2 = new Vector2[n];
			o.Colors1 = new AbstractMeshData.Color[n];
			o.BoneIndices = new VertexStreamData.BoneIndex[n];
			o.BoneWeights = new VertexStreamData.BoneWeight[n];
			for (int i = 0; i < n; i++)
			{
				int s = list[i];
				o.Positions[i] = g.Positions[s]; o.Normals[i] = g.Normals[s]; o.Tangents[i] = g.Tangents[s];
				o.Uv1[i] = g.Uv1[s]; o.Uv2[i] = g.Uv2[s]; o.Colors1[i] = g.Colors1[s];
				o.BoneIndices[i] = g.BoneIndices[s]; o.BoneWeights[i] = g.BoneWeights[s];
			}
			o.Indices = tris.Select(x => map[x]).ToArray();
			var mn = new Vector3(float.MaxValue); var mx = new Vector3(float.MinValue);
			var bones = new HashSet<int>();
			for (int i = 0; i < n; i++)
			{
				mn = Vector3.Min(mn, o.Positions[i]); mx = Vector3.Max(mx, o.Positions[i]);
				var bi = o.BoneIndices[i];
				bones.Add(bi.B1); bones.Add(bi.B2); bones.Add(bi.B3); bones.Add(bi.B4);
			}
			o.Min = mn; o.Max = mx; o.BonesUsed = bones.Count;
			return o;
		}

		private static VertexStreamData.SnormShort4 QuatFromColumns(Vector3 c0, Vector3 c1, Vector3 c2)
		{
			float m00 = c0.X, m10 = c0.Y, m20 = c0.Z;
			float m01 = c1.X, m11 = c1.Y, m21 = c1.Z;
			float m02 = c2.X, m12 = c2.Y, m22 = c2.Z;
			float tr = m00 + m11 + m22;
			float x, y, z, w;
			if (tr > 0)
			{
				float s = (float) Math.Sqrt(tr + 1.0) * 2f;
				w = 0.25f * s; x = (m21 - m12) / s; y = (m02 - m20) / s; z = (m10 - m01) / s;
			}
			else if (m00 > m11 && m00 > m22)
			{
				float s = (float) Math.Sqrt(1.0 + m00 - m11 - m22) * 2f;
				w = (m21 - m12) / s; x = 0.25f * s; y = (m01 + m10) / s; z = (m02 + m20) / s;
			}
			else if (m11 > m22)
			{
				float s = (float) Math.Sqrt(1.0 + m11 - m00 - m22) * 2f;
				w = (m02 - m20) / s; x = (m01 + m10) / s; y = 0.25f * s; z = (m12 + m21) / s;
			}
			else
			{
				float s = (float) Math.Sqrt(1.0 + m22 - m00 - m11) * 2f;
				w = (m10 - m01) / s; x = (m02 + m20) / s; y = (m12 + m21) / s; z = 0.25f * s;
			}
			if (w < 0) { x = -x; y = -y; z = -z; w = -w; }
			var q = new VertexStreamData.SnormShort4();
			q.X = x; q.Y = y; q.Z = z; q.W = w;
			return q;
		}

		// ------------------------------------------------------------ verbatim clone
		private static void MesoCloneFrom(this Metamesh mm, Ctx ctx, Metamesh src)
		{
			mm.UnknownFloat = src.UnknownFloat;
			mm.UnknownString = src.UnknownString;
			mm.UnknownUint = src.UnknownUint;
			mm.ClothUint = src.ClothUint;
			mm.ClothString = src.ClothString;
			mm.UnknownBool1 = src.UnknownBool1;
			mm.UnknownBool2 = src.UnknownBool2;
			mm.MetaVersion = src.MetaVersion;
			mm.Material = src.Material;
			mm.ClothMetamesh = src.ClothMetamesh;
			mm.Original = src.Original;
			mm.Variations = new List<Guid>(src.Variations);

			// the segments belong to the asset, not the submesh; re-own them by the new
			// submesh guids and register them so the writer copies the bytes verbatim
			var srcByGuid = new Dictionary<Guid, Guid>();
			int i = 0;
			foreach (var m in src.Meshes)
			{
				var c = new Mesh();
				c.IsCompleteMesh = m.IsCompleteMesh;
				c.Lod = m.Lod;
				c.SubVersion = m.SubVersion;
				c.UnknownUint1 = m.UnknownUint1;
				c.SecondMaterial = new AssetDependence<Material>(m.SecondMaterial.Guid);
				c.Material = new AssetDependence<Material>(m.Material.Guid);
				c.Guid = ctx.NewGuid();
				c.Name = i == 0 ? mm.Name : mm.Name + "." + i;
				c.UnknownUInt2 = m.UnknownUInt2;
				c.Flags = new List<string>(m.Flags);
				c.FactorColor = m.FactorColor;
				c.Factor2Color = m.Factor2Color;
				c.VectorArgument = m.VectorArgument;
				c.VectorArgument2 = m.VectorArgument2;
				c.VertexKeyCount = m.VertexKeyCount;
				c.PositionCount = m.PositionCount;
				c.FaceCount = m.FaceCount;
				c.VertexCount = m.VertexCount;
				c.SkinDataSize = m.SkinDataSize;
				c.BoundingBox = m.BoundingBox;
				c.UnknownInt2 = m.UnknownInt2;
				c.MaterialFlags = new List<string>(m.MaterialFlags);
				c.UnknownFloat1 = m.UnknownFloat1;
				c.ClothingMaterial = m.ClothingMaterial;
				c.UnknownInt3 = m.UnknownInt3;
				c.UnknownBool1 = m.UnknownBool1;
				c.UnknownBool2 = m.UnknownBool2;
				c.UnknownBool3 = m.UnknownBool3;
				c.EditData = m.EditData;
				c.VertexStream = m.VertexStream;
				srcByGuid[m.Guid] = c.Guid;
				mm.Meshes.Add(c);
				i++;
			}
			foreach (var seg in src.TypelessDataSegments)
			{
				if (srcByGuid.TryGetValue(seg.OwnerGuid, out var ng))
					seg.OwnerGuid = ng;
				mm.TypelessDataSegments.Add(seg);
			}
			if (src.EditmodeMisc != null && !mm.TypelessDataSegments.Contains(src.EditmodeMisc))
			{
				src.EditmodeMisc.OwnerGuid = mm.Guid;
				mm.EditmodeMisc = src.EditmodeMisc;
				mm.TypelessDataSegments.Insert(0, src.EditmodeMisc);
			}
		}

		private static Guid kMiscOwner;

		// -------------------------------------------------------------- mgeo input
		private class Geo
		{
			public int Count;
			public Vector3[] Positions;
			public Vector3[] Normals;
			public Vector4[] Tangents;
			public Vector2[] Uv1;
			public Vector2[] Uv2;
			public AbstractMeshData.Color[] Colors1;
			public VertexStreamData.BoneIndex[] BoneIndices;
			public VertexStreamData.BoneWeight[] BoneWeights;
			public int[] Indices;
			public Vector3 Min, Max;
			public int BonesUsed;
		}

		private static Geo ReadMgeo(string path)
		{
			var d = File.ReadAllBytes(path);
			int magic = BitConverter.ToInt32(d, 0);
			if (magic != 0x4F45474D) throw new Exception("not an mgeo file: " + path);
			int n = BitConverter.ToInt32(d, 4);
			int m = BitConverter.ToInt32(d, 8);
			int off = 12;
			float[] TakeFloats(int count) { var a = new float[count]; Buffer.BlockCopy(d, off, a, 0, count * 4); off += count * 4; return a; }
			byte[] TakeBytes(int count) { var a = new byte[count]; Buffer.BlockCopy(d, off, a, 0, count); off += count; return a; }

			var g = new Geo { Count = n };
			var pf = TakeFloats(n * 3);
			var nf = TakeFloats(n * 3);
			var tf = TakeFloats(n * 4);
			var u1 = TakeFloats(n * 2);
			var u2 = TakeFloats(n * 2);
			var col = TakeBytes(n * 4);
			var bi = TakeBytes(n * 4);
			var bw = TakeBytes(n * 4);
			g.Indices = new int[m];
			Buffer.BlockCopy(d, off, g.Indices, 0, m * 4);
			off += m * 4;

			g.Positions = new Vector3[n];
			g.Normals = new Vector3[n];
			g.Tangents = new Vector4[n];
			g.Uv1 = new Vector2[n];
			g.Uv2 = new Vector2[n];
			g.Colors1 = new AbstractMeshData.Color[n];
			g.BoneIndices = new VertexStreamData.BoneIndex[n];
			g.BoneWeights = new VertexStreamData.BoneWeight[n];
			var mn = new Vector3(float.MaxValue);
			var mx = new Vector3(float.MinValue);
			var bones = new HashSet<int>();
			for (int i = 0; i < n; i++)
			{
				g.Positions[i] = new Vector3(pf[i * 3], pf[i * 3 + 1], pf[i * 3 + 2]);
				g.Normals[i] = Vector3.Normalize(new Vector3(nf[i * 3], nf[i * 3 + 1], nf[i * 3 + 2]));
				g.Tangents[i] = new Vector4(tf[i * 4], tf[i * 4 + 1], tf[i * 4 + 2], tf[i * 4 + 3]);
				g.Uv1[i] = new Vector2(u1[i * 2], u1[i * 2 + 1]);
				g.Uv2[i] = new Vector2(u2[i * 2], u2[i * 2 + 1]);
				g.Colors1[i] = new AbstractMeshData.Color { R = col[i * 4], G = col[i * 4 + 1], B = col[i * 4 + 2], A = col[i * 4 + 3] };
				g.BoneIndices[i] = new VertexStreamData.BoneIndex { B1 = bi[i * 4], B2 = bi[i * 4 + 1], B3 = bi[i * 4 + 2], B4 = bi[i * 4 + 3] };
				g.BoneWeights[i] = new VertexStreamData.BoneWeight { W1 = bw[i * 4], W2 = bw[i * 4 + 1], W3 = bw[i * 4 + 2], W4 = bw[i * 4 + 3] };
				mn = Vector3.Min(mn, g.Positions[i]);
				mx = Vector3.Max(mx, g.Positions[i]);
				bones.Add(bi[i * 4]); bones.Add(bi[i * 4 + 1]); bones.Add(bi[i * 4 + 2]); bones.Add(bi[i * 4 + 3]);
			}
			g.Min = mn;
			g.Max = mx;
			g.BonesUsed = bones.Count;
			return g;
		}

	}
}
