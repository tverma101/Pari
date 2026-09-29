import { normalizeCustomStyle, type CustomStyle } from "@/lib/styles/customStyles";
import { nativeBridgeAvailable, requestNativeBridge } from "@/lib/platform/nativeBridge";

export async function loadCustomStyles(): Promise<CustomStyle[]> {
  if (!nativeBridgeAvailable()) return [];
  const result = await requestNativeBridge("loadCustomStyles");
  if (!result || typeof result !== "object") return [];
  const styles = (result as { styles?: unknown }).styles;
  if (!Array.isArray(styles)) return [];
  return styles.map(normalizeCustomStyle).filter((style): style is CustomStyle => style !== null);
}
