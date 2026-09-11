// Minimal stand-ins for the JetBrains.Annotations package used by TpacTool.Lib,
// so the library builds without any NuGet dependency.
namespace JetBrains.Annotations
{
	[System.AttributeUsage(System.AttributeTargets.All)]
	internal sealed class NotNullAttribute : System.Attribute { }

	[System.AttributeUsage(System.AttributeTargets.All)]
	internal sealed class CanBeNullAttribute : System.Attribute { }

	[System.AttributeUsage(System.AttributeTargets.All)]
	internal sealed class PublicAPIAttribute : System.Attribute { }

	[System.AttributeUsage(System.AttributeTargets.All)]
	internal sealed class UsedImplicitlyAttribute : System.Attribute { }
}
