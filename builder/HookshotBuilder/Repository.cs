using System;
using System.IO;
using System.Text.RegularExpressions;

/// (hookshot) The GitHub repository releases come from, as owner/name: tools/repository.txt, written when the release is
/// packaged from the repository its CI ran in (scripts/release_parts.py package), else NotRexed/Hookshot. A fork's Builder
/// then updates from the fork. nx2/version.py repository() is the same rule for the game's own update check.
static class Repository
{
    const string Default = "NotRexed/Hookshot";
    static readonly Lazy<string> name = new(Read);
    public static string Name => name.Value;

    static string Read()
    {
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "tools", "repository.txt");
            if (File.Exists(path))
            {
                var line = File.ReadAllText(path).Trim();
                if (Regex.IsMatch(line, "^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")) return line;
            }
        }
        catch (Exception) { }   // (an unreadable file is the default, not a failed update check)
        return Default;
    }
}
