"""Apply writer-fidelity patches to the vendored TpacTool.Lib sources."""
import io, os, sys

ROOT = r".\TpacTool-master\TpacTool.Lib"


def patch(rel, pairs, required=True):
    p = os.path.join(ROOT, rel)
    s = io.open(p, encoding="utf-8-sig").read()
    for old, new in pairs:
        if old not in s:
            print(f"  !! NOT FOUND in {rel}: {old[:70]!r}")
            if required:
                sys.exit(1)
            continue
        if s.count(old) != 1:
            print(f"  !! NOT UNIQUE ({s.count(old)}) in {rel}: {old[:70]!r}")
            sys.exit(1)
        s = s.replace(old, new)
    io.open(p, "w", encoding="utf-8-sig", newline="").write(s)
    print("  patched", rel)


# 1) AssetItem: keep the unconsumed metadata tail and re-append it on write
patch("Package/AssetItem.cs", [
    ("""		public long MetadataChecksum { set; get; }""",
     """		public long MetadataChecksum { set; get; }

		// [MbTool patch] metadata bytes past the end of what the typed reader understood.
		// Re-appended verbatim by WriteMetadata so newer metadata versions round-trip.
		public byte[] MetadataTail { set; get; }

		public int MetadataParsedSize { set; get; }"""),
    ("""				WriteMetadata(stream);
				stream.Flush();
				return memStream.ToArray();""",
     """				WriteMetadata(stream);
				if (MetadataTail != null && MetadataTail.Length > 0)
					stream.Write(MetadataTail);
				stream.Flush();
				return memStream.ToArray();"""),
])

# 2) AssetPackage.Load: record how much the typed reader consumed
patch("Package/AssetPackage.cs", [
    ("""				using (var metadataStream = rawMetadata.CreateBinaryReader())
				{
					assetItem.ReadMetadata(metadataStream, (int)metadataSize);
				}""",
     """				using (var metadataStream = rawMetadata.CreateBinaryReader())
				{
					assetItem.ReadMetadata(metadataStream, (int)metadataSize);
					var consumed = (int)metadataStream.BaseStream.Position;
					assetItem.MetadataParsedSize = consumed;
					if (consumed >= 0 && consumed < rawMetadata.Length)
					{
						var tail = new byte[rawMetadata.Length - consumed];
						Array.Copy(rawMetadata, consumed, tail, 0, tail.Length);
						assetItem.MetadataTail = tail;
					}
				}"""),
])

# 3) Mesh: remember the mesh metadata sub-version (2 in modern packages, writer used to hardcode 1)
patch("Model/Mesh.cs", [
    ("""		public bool IsCompleteMesh { set; get; }""",
     """		public bool IsCompleteMesh { set; get; }

		// [MbTool patch] mesh metadata sub-version; 1 before 1.4.x, 2 since.
		public uint SubVersion { set; get; }"""),
    ("""			var subVersion = stream.ReadUInt32();""",
     """			SubVersion = stream.ReadUInt32();"""),
    ("""			if (subVersion >= 1)""",
     """			if (SubVersion >= 1)"""),
    ("""			stream.Write((int) 1);
			stream.Write(Guid);""",
     """			stream.Write(SubVersion);
			stream.Write(Guid);"""),
    ("""			IsCompleteMesh = true;
			UnknownUint1 = 2;""",
     """			IsCompleteMesh = true;
			SubVersion = 2;
			UnknownUint1 = 2;"""),
])

# 4) Metamesh: keep the metadata version
patch("Model/Metamesh.cs", [
    ("""		public Guid Material { set; get; } // not sure. but billboard texture will ref the same guid""",
     """		// [MbTool patch] metamesh metadata version (1 or 2 in current packages)
		public uint MetaVersion { set; get; }

		public Guid Material { set; get; } // not sure. but billboard texture will ref the same guid"""),
    ("""			this.Material = Guid.Empty;""",
     """			this.MetaVersion = 1;
			this.Material = Guid.Empty;"""),
    ("""			var version = stream.ReadUInt32();
			Material = stream.ReadGuid();""",
     """			MetaVersion = stream.ReadUInt32();
			var version = MetaVersion;
			Material = stream.ReadGuid();"""),
    ("""		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write(1);
			stream.Write(Material);""",
     """		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write(MetaVersion);
			stream.Write(Material);"""),
])

# 5) Texture: keep the metadata version (writer used to hardcode 2)
patch("Texture/Texture.cs", [
    ("""		[NotNull]
		public AssetDependence<Material> BillboardMaterial { set; get; }""",
     """		// [MbTool patch] texture metadata version (3 in current packages)
		public uint MetaVersion { set; get; }

		[NotNull]
		public AssetDependence<Material> BillboardMaterial { set; get; }"""),
    ("""			BillboardMaterial = AssetDependence<Material>.CreateEmpty();
			Source = String.Empty;""",
     """			MetaVersion = 2;
			BillboardMaterial = AssetDependence<Material>.CreateEmpty();
			Source = String.Empty;"""),
    ("""			var pos = stream.BaseStream.Position;
			var version = stream.ReadUInt32();""",
     """			var pos = stream.BaseStream.Position;
			MetaVersion = stream.ReadUInt32();
			var version = MetaVersion;"""),
    ("""		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write((uint) 2);""",
     """		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write(MetaVersion);"""),
    ("""			stream.Write(GeneratedAssets.Count);""",
     """			stream.Write(GeneratedAssets != null ? GeneratedAssets.Count : 0);"""),
    ("""			for (var i = 0; i < GeneratedAssets.Count; i++)
			{
				var tuple = GeneratedAssets[i];""",
     """			for (var i = 0; GeneratedAssets != null && i < GeneratedAssets.Count; i++)
			{
				var tuple = GeneratedAssets[i];"""),
])

# 6) Skeleton: keep the metadata version (writer hardcoded 0)
patch("Skeleton/Skeleton.cs", [
    ("""		// ignore?
		public bool UnknownBool { set; get; }""",
     """		// [MbTool patch] skeleton metadata version
		public uint MetaVersion { set; get; }

		// ignore?
		public bool UnknownBool { set; get; }"""),
    ("""			var version = stream.ReadUInt32();
			UnknownBool = stream.ReadBoolean();""",
     """			MetaVersion = stream.ReadUInt32();
			UnknownBool = stream.ReadBoolean();"""),
    ("""		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write((int) 0);""",
     """		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write(MetaVersion);"""),
])

# 7) Material: add a full serializer (TpacTool only had a reader)
patch("Material/Material.cs", [
    ("""		public Guid BillboardGuid { set; get; }""",
     """		// [MbTool patch] versions needed to serialize metadata back out
		public uint MetaVersion { set; get; }

		public uint SubVersion { set; get; }

		public Guid BillboardGuid { set; get; }"""),
    ("""			var version = stream.ReadUInt32();
			BillboardGuid = stream.ReadGuid();
			var subVersion = stream.ReadUInt32();""",
     """			MetaVersion = stream.ReadUInt32();
			BillboardGuid = stream.ReadGuid();
			SubVersion = stream.ReadUInt32();"""),
    ("""			ExtraMaterialSettings.Load(stream, subVersion);""",
     """			ExtraMaterialSettings.Load(stream, SubVersion);"""),
    ("""		public class ExtraMaterialSetting
		{""",
     """		// [MbTool patch] full metadata serializer, mirroring ReadMetadata above.
		public override void WriteMetadata(BinaryWriter stream)
		{
			stream.Write(MetaVersion);
			stream.Write(BillboardGuid);
			stream.Write(SubVersion);
			stream.Write(UnknownUint1);
			stream.WriteStringList(Flags);
			stream.Write(UnknownUint2);
			stream.WriteStringList(VertexLayoutFlags);
			stream.WriteSizedString(BlendMode);
			stream.Write(Shader.Guid);
			stream.Write(Textures.Count);
			foreach (var pair in Textures)
			{
				stream.Write(pair.Key);
				stream.Write(pair.Value.Guid);
			}
			stream.Write(AlphaTest);
			stream.WriteStringList(ShaderMaterialFlags);
			ExtraMaterialSettings.Write(stream, SubVersion);
		}

		public class ExtraMaterialSetting
		{"""),
    ("""			internal void Load(BinaryReader stream, uint subVersion = 2)
			{""",
     """			internal void Write(BinaryWriter stream, uint subVersion = 2)
			{
				stream.Write(AreamapScale);
				stream.Write(AreamapAmount);
				stream.Write(DetailnormalScale);
				stream.Write(NormalmapPower);
				stream.Write(MeshVectorArgument);
				stream.Write(MeshVectorArgument2);
				stream.Write(MeshFactorColorMultiplier);
				stream.Write(MeshFactor2ColorMultiplier);
				stream.Write(RenderOrder);
				stream.Write(MipmapBias);
				stream.Write(SpecularCoef);
				stream.Write(GlossCoef);
				stream.Write(ParallaxAmount);
				if (subVersion >= 1)
					stream.Write(ParallaxOffset);
				stream.Write(AmbientOcclusionCoef);
				if (subVersion >= 2)
					stream.Write(ExposureCompensation);
			}

			internal void Load(BinaryReader stream, uint subVersion = 2)
			{"""),
])
print("all patches applied")
