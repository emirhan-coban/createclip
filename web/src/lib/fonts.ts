// Fonts shared by the text layers; the families are declared in index.css, the files are autoshorts/fonts/*.ttf.
export type FontKey = "montserrat" | "poppins" | "gabarito";
export const FONTS: Record<FontKey, { label: string; family: string; weight: number }> = {
  montserrat: { label: "Montserrat", family: "KMontserrat", weight: 800 },
  poppins: { label: "Poppins", family: "KPoppins", weight: 700 },
  gabarito: { label: "Gabarito", family: "KGabarito", weight: 800 },
};
