"""RuleEngine: loader (hard sign-off gate), matcher, conflict resolution. Batch M3.7.
این پوشه YAMLهای قوانین را بارگذاری، چک، match و حل تعارض می‌کند.
YAML قانون → loader چک می‌کند → FeatureEngine surprise می‌دهد → matcher شرط را چک می‌کند → conflict حل می‌شود → Activation برای scoring و خروجی نهایی.
"""
