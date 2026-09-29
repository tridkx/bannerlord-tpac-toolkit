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
	/// 骨骼动画的离线读取（SkeletalAnimation / AnimationClip）。
	///
	/// mbtool 原本只覆盖几何 / 材质 / 贴图 / 骨架，这两类资产一直没暴露入口，
	/// 于是"带动画的离线预览"整条路走不通，只能进游戏看。
	/// TpacTool.Lib 其实**已经完整实现**了它们的解析（SkeletalAnimation、
	/// AnimationDefinitionData、OptimizedAnimation），这里只是把它调出来，
	/// dump 成 JSON 交给 Blender / 实时查看器。
	///
	/// 链路：AnimationClip（名字，如 inventory_idle）
	///         --.Animation guid--> SkeletalAnimation（anim_inventory_idle）
	///         --.Definition.Data--> AnimationDefinitionData（每根骨的四元数关键帧）
	/// </summary>
	internal static class Anim
	{
		private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

		private static string F(float v) => v.ToString("R", Inv);
		private static string V3(Vector3 v) => "[" + F(v.X) + "," + F(v.Y) + "," + F(v.Z) + "]";
		private static string V4(Vector4 v) => "[" + F(v.X) + "," + F(v.Y) + "," + F(v.Z) + "," + F(v.W) + "]";
		private static string Q(Quaternion q) => "[" + F(q.X) + "," + F(q.Y) + "," + F(q.Z) + "," + F(q.W) + "]";

		private static AssetPackage Open(string path, bool data) => new AssetPackage(path, true, data);

		// ==================================================================
		// animlist <animations.tpac> [filter]
		// ==================================================================
		public static int List(string[] a)
		{
			if (a.Length < 2) { Console.WriteLine("usage: animlist <animations.tpac> [filter]"); return 1; }
			string filter = a.Length > 2 ? a[2] : null;
			var pkg = Open(a[1], false);
			Console.WriteLine($"# {a[1]}  {pkg.Items.Count} assets");
			int n = 0;
			foreach (var sa in pkg.Items.OfType<SkeletalAnimation>().OrderBy(x => x.Name, StringComparer.Ordinal))
			{
				if (filter != null && sa.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0) continue;
				Console.WriteLine($"SkeletalAnimation  {sa.Name,-56} {sa.Guid} bones={sa.BoneNum,-3} dur={sa.Duration}");
				n++;
			}
			Console.WriteLine($"# {n} matched of {pkg.Items.Count}");
			return 0;
		}

		// ==================================================================
		// cliplist <animation_clips.tpac> [filter]
		// ==================================================================
		public static int ClipList(string[] a)
		{
			if (a.Length < 2) { Console.WriteLine("usage: cliplist <animation_clips.tpac> [filter]"); return 1; }
			string filter = a.Length > 2 ? a[2] : null;
			var pkg = Open(a[1], false);
			Console.WriteLine($"# {a[1]}  {pkg.Items.Count} assets");
			int n = 0;
			foreach (var c in pkg.Items.OfType<AnimationClip>().OrderBy(x => x.Name, StringComparer.Ordinal))
			{
				if (filter != null && c.Name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0) continue;
				// flags/priority 一并打出来：离线预览器要用 clip 的 duration 当
				// "这段动画真正播多久"的依据（见 preview/build_anim_index.py），
				// 用 cyclic 决定循环播放时要不要跳过重复的首尾帧。
				Console.WriteLine($"AnimationClip  {c.Name,-56} dur={c.Duration,-8:F3} anim={c.Animation} flags=[{string.Join(",", c.Flags)}] prio={c.Priority}");
				n++;
			}
			Console.WriteLine($"# {n} matched of {pkg.Items.Count}");
			return 0;
		}

		// ==================================================================
		// clip <animation_clips.tpac> <name|guid>
		// ==================================================================
		public static int Clip(string[] a)
		{
			if (a.Length < 3) { Console.WriteLine("usage: clip <animation_clips.tpac> <name|guid>"); return 1; }
			var pkg = Open(a[1], false);
			var c = FindClip(pkg, a[2]);
			if (c == null) { Console.WriteLine("clip not found: " + a[2]); return 1; }

			Console.WriteLine($"AnimationClip '{c.Name}' guid={c.Guid} version={c.Version}");
			Console.WriteLine($"  duration={c.Duration} animation={c.Animation}");
			Console.WriteLine($"  flags=[{string.Join(",", c.Flags)}]");
			Console.WriteLine($"  blendIn={c.BlendInPeriod} blendOut={c.BlendOutPeriod} priority={c.Priority}");
			Console.WriteLine($"  sound={c.SoundCode} voice={c.VoiceCode} facial={c.FacialAnimationId}");
			Console.WriteLine($"  blendsWith='{c.BlendsWithAction}' continuesWith='{c.ContinueWithAction}'");
			Console.WriteLine($"  leftHandPose={c.LeftHandPose} rightHandPose={c.RightHandPose} combat={c.CombatParameterId}");
			Console.WriteLine($"  stepPoints={V4(c.StepPoints)} doNotInterpolate={c.DoNotInterpolate}");
			foreach (var u in c.ClipUsages)
				Console.WriteLine($"  usage: {u.Type} {UsageDetail(u)}");
			return 0;
		}

		private static string UsageDetail(AnimationClip.ClipUsage u)
		{
			if (u is AnimationClip.DisplacementUsage d)
				return $"vec={V3(d.DisplacementVector)} endProgress={F(d.DisplacementEndProgress)}";
			if (u is AnimationClip.QuadMovementUsage q)
				return $"loop={F(q.LoopDisplacement)} pace=[{F(q.PaceSwitchLimitMin)},{F(q.PaceSwitchLimitMax)}]";
			if (u is AnimationClip.BipMovIkUsage b)
				return $"loop={F(b.LoopDisplacement)} adj=[{F(b.AdjustingStart0)},{F(b.AdjustingStart1)}]";
			if (u is AnimationClip.BlendUsage bl)
				return $"start={F(bl.BlendStartProgress)} end={F(bl.BlendEndProgress)}";
			if (u is AnimationClip.MountChangeUsage m)
				return $"scaleBlend=[{F(m.ScaleBlendStartProgress)},{F(m.ScaleBlendEndProgress)}]";
			return "";
		}

		private static AnimationClip FindClip(AssetPackage pkg, string key)
		{
			Guid g;
			if (Guid.TryParse(key, out g))
				return pkg.Items.OfType<AnimationClip>().FirstOrDefault(x => x.Guid == g);
			return pkg.Items.OfType<AnimationClip>().FirstOrDefault(x => x.Name == key)
				?? pkg.Items.OfType<AnimationClip>().FirstOrDefault(
						x => x.Name.IndexOf(key, StringComparison.OrdinalIgnoreCase) >= 0);
		}

		private static SkeletalAnimation FindAnim(AssetPackage pkg, string key)
		{
			Guid g;
			if (Guid.TryParse(key, out g))
				return pkg.Items.OfType<SkeletalAnimation>().FirstOrDefault(x => x.Guid == g);
			return pkg.Items.OfType<SkeletalAnimation>().FirstOrDefault(x => x.Name == key)
				?? pkg.Items.OfType<SkeletalAnimation>().FirstOrDefault(
						x => x.Name.IndexOf(key, StringComparison.OrdinalIgnoreCase) >= 0);
		}

		// ==================================================================
		// anim <animations.tpac> <name|guid> [out.json] [skeletons.tpac]
		// ==================================================================
		public static int Dump(string[] a)
		{
			if (a.Length < 3) { Console.WriteLine("usage: anim <animations.tpac> <name|guid> [out.json] [skeletons.tpac]"); return 1; }
			var pkg = Open(a[1], true);
			var sa = FindAnim(pkg, a[2]);
			if (sa == null) { Console.WriteLine("animation not found: " + a[2]); return 1; }

			var def = sa.Definition != null ? sa.Definition.Data : null;

			// 骨架（骨名 / 父索引 / 静置矩阵）—— 用来把 BoneAnims 的下标翻译成骨名
			SkeletonDefinitionData skelDef = null;
			if (a.Length > 4 && a[4].Length > 0 && File.Exists(a[4]))
			{
				var spkg = Open(a[4], true);
				var sk = spkg.Items.OfType<Skeleton>().FirstOrDefault(x => x.Guid == sa.Skeleton)
						 ?? spkg.Items.OfType<Skeleton>().FirstOrDefault(x => x.Name == "human_skeleton");
				if (sk?.Definition != null) skelDef = sk.Definition.Data;
			}

			int rotFrames = 0, posFrames = 0;
			if (def != null)
			{
				foreach (var b in def.BoneAnims)
				{
					rotFrames += b.RotationFrames.Count;
					posFrames += b.PositionFrames.Count;
				}
			}

			Console.WriteLine($"SkeletalAnimation '{sa.Name}' guid={sa.Guid} version={sa.Version}");
			Console.WriteLine($"  geometry={sa.GeometryGuid} skeleton={sa.Skeleton}");
			Console.WriteLine($"  boneNum={sa.BoneNum} duration={sa.Duration} unknownBool={sa.UnknownBool}");
			if (def == null)
			{
				Console.WriteLine("  !! definition data is NULL (no segment loaded)");
			}
			else
			{
				Console.WriteLine($"  defName='{def.Name}' boneAnims={def.BoneAnims.Count}");
				Console.WriteLine($"  rootPositionFrames={def.RootPositionFrames.Count} rootScaleFrames={def.RootScaleFrames.Count}");
				Console.WriteLine($"  total rotationFrames={rotFrames} positionFrames={posFrames}");
				for (int i = 0; i < Math.Min(def.BoneAnims.Count, 5); i++)
				{
					var b = def.BoneAnims[i];
					string nm = (skelDef != null && i < skelDef.Bones.Count) ? skelDef.Bones[i].Name : "?";
					string first = b.RotationFrames.Count > 0 ? Q(b.RotationFrames.First().Value.Value) : "-";
					Console.WriteLine($"    bone[{i,3}] {nm,-32} rot={b.RotationFrames.Count,-4} pos={b.PositionFrames.Count,-4} q0={first}");
				}
			}
			if (skelDef != null)
				Console.WriteLine($"  skeleton '{skelDef.Name}' bones={skelDef.Bones.Count}");

			if (a.Length > 3 && a[3].Length > 0)
			{
				WriteJson(a[3], sa, def, skelDef);
				Console.WriteLine($"  -> wrote {a[3]}");
			}
			return 0;
		}

		// ==================================================================
		// skeljson <skeletons.tpac> <name|guid> <out.json>
		// ==================================================================
		public static int SkelJson(string[] a)
		{
			if (a.Length < 4) { Console.WriteLine("usage: skeljson <skeletons.tpac> <name|guid> <out.json>"); return 1; }
			var pkg = Open(a[1], true);
			Guid g;
			Skeleton sk;
			if (Guid.TryParse(a[2], out g))
				sk = pkg.Items.OfType<Skeleton>().FirstOrDefault(x => x.Guid == g);
			else
				sk = pkg.Items.OfType<Skeleton>().FirstOrDefault(x => x.Name == a[2]);
			if (sk?.Definition == null) { Console.WriteLine("skeleton not found: " + a[2]); return 1; }

			var d = sk.Definition.Data;
			var parents = d.CreateParentLookup();
			var sb = new StringBuilder();
			sb.Append("{\n");
			sb.Append($"  \"name\": \"{Esc(sk.Name)}\",\n");
			sb.Append($"  \"guid\": \"{sk.Guid}\",\n");
			sb.Append($"  \"geometryGuid\": \"{sk.GeometryGuid}\",\n");
			sb.Append($"  \"boneCount\": {d.Bones.Count},\n");
			sb.Append("  \"bones\": [\n");
			for (int i = 0; i < d.Bones.Count; i++)
			{
				var b = d.Bones[i];
				var m = b.RestFrame;
				sb.Append($"    {{\"i\":{i},\"name\":\"{Esc(b.Name)}\",\"parent\":{parents[i]},\"rest\":[");
				sb.Append($"{F(m.M11)},{F(m.M12)},{F(m.M13)},{F(m.M14)},");
				sb.Append($"{F(m.M21)},{F(m.M22)},{F(m.M23)},{F(m.M24)},");
				sb.Append($"{F(m.M31)},{F(m.M32)},{F(m.M33)},{F(m.M34)},");
				sb.Append($"{F(m.M41)},{F(m.M42)},{F(m.M43)},{F(m.M44)}]}}");
				sb.Append(i + 1 < d.Bones.Count ? ",\n" : "\n");
			}
			sb.Append("  ]\n}\n");
			File.WriteAllText(a[3], sb.ToString(), new UTF8Encoding(false));
			Console.WriteLine($"skeleton '{sk.Name}' bones={d.Bones.Count} -> {a[3]}");
			return 0;
		}

		private static void WriteJson(string path, SkeletalAnimation sa, AnimationDefinitionData def, SkeletonDefinitionData skel)
		{
			var sb = new StringBuilder(1 << 20);
			sb.Append("{\n");
			sb.Append($"  \"name\": \"{Esc(sa.Name)}\",\n");
			sb.Append($"  \"guid\": \"{sa.Guid}\",\n");
			sb.Append($"  \"geometryGuid\": \"{sa.GeometryGuid}\",\n");
			sb.Append($"  \"skeletonGuid\": \"{sa.Skeleton}\",\n");
			sb.Append($"  \"skeletonName\": \"{Esc(skel != null ? skel.Name : "")}\",\n");
			sb.Append($"  \"boneNum\": {sa.BoneNum},\n");
			sb.Append($"  \"duration\": {sa.Duration},\n");
			sb.Append($"  \"unknownBool\": {(sa.UnknownBool ? "true" : "false")},\n");

			// 骨架：骨名 / 父索引 / 静置矩阵
			sb.Append("  \"bones\": [");
			if (skel != null)
			{
				var parents = skel.CreateParentLookup();
				sb.Append("\n");
				for (int i = 0; i < skel.Bones.Count; i++)
				{
					var b = skel.Bones[i];
					var m = b.RestFrame;
					sb.Append($"    {{\"i\":{i},\"name\":\"{Esc(b.Name)}\",\"parent\":{parents[i]},\"rest\":[");
					sb.Append($"{F(m.M11)},{F(m.M12)},{F(m.M13)},{F(m.M14)},");
					sb.Append($"{F(m.M21)},{F(m.M22)},{F(m.M23)},{F(m.M24)},");
					sb.Append($"{F(m.M31)},{F(m.M32)},{F(m.M33)},{F(m.M34)},");
					sb.Append($"{F(m.M41)},{F(m.M42)},{F(m.M43)},{F(m.M44)}]}}");
					sb.Append(i + 1 < skel.Bones.Count ? ",\n" : "\n");
				}
				sb.Append("  ],\n");
			}
			else
			{
				sb.Append("],\n");
			}

			if (def == null)
			{
				sb.Append("  \"rootPosition\": [],\n  \"rootScale\": [],\n  \"boneAnims\": []\n}\n");
				File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
				return;
			}

			sb.Append($"  \"defName\": \"{Esc(def.Name)}\",\n");

			sb.Append("  \"rootPosition\": [");
			WriteV4Frames(sb, def.RootPositionFrames);
			sb.Append("],\n");

			sb.Append("  \"rootScale\": [");
			{
				bool first = true;
				foreach (var kv in def.RootScaleFrames)
				{
					if (!first) sb.Append(",");
					first = false;
					sb.Append($"{{\"t\":{F(kv.Value.Time)},\"v\":{V3(kv.Value.Value)}}}");
				}
			}
			sb.Append("],\n");

			sb.Append("  \"boneAnims\": [\n");
			for (int i = 0; i < def.BoneAnims.Count; i++)
			{
				var b = def.BoneAnims[i];
				sb.Append($"    {{\"i\":{i},\"rot\":[");
				bool first = true;
				foreach (var kv in b.RotationFrames)
				{
					if (!first) sb.Append(",");
					first = false;
					sb.Append($"{{\"t\":{F(kv.Value.Time)},\"q\":{Q(kv.Value.Value)}}}");
				}
				sb.Append("],\"pos\":[");
				first = true;
				foreach (var kv in b.PositionFrames)
				{
					if (!first) sb.Append(",");
					first = false;
					sb.Append($"{{\"t\":{F(kv.Value.Time)},\"v\":{V4(kv.Value.Value)}}}");
				}
				sb.Append("]}");
				sb.Append(i + 1 < def.BoneAnims.Count ? ",\n" : "\n");
			}
			sb.Append("  ]\n}\n");

			File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
		}

		private static void WriteV4Frames(StringBuilder sb, SortedList<float, AnimationFrame<Vector4>> frames)
		{
			bool first = true;
			foreach (var kv in frames)
			{
				if (!first) sb.Append(",");
				first = false;
				sb.Append($"{{\"t\":{F(kv.Value.Time)},\"v\":{V4(kv.Value.Value)}}}");
			}
		}

		private static string Esc(string s) => s == null ? "" : s.Replace("\\", "\\\\").Replace("\"", "\\\"");
	}
}