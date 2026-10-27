import {
  Armchair,
  Baby,
  ChefHat,
  Droplets,
  Flower,
  Flower2,
  Footprints,
  Heart,
  HeartHandshake,
  Lightbulb,
  MessageCircle,
  Moon,
  MoonStar,
  Pill,
  Soup,
  Sprout,
  Sun,
  Sunrise,
  type LucideIcon,
} from "lucide-react";

/** Illustration for a card (the server names a lucide icon; words are always shown next to it). */
export const KUDOS_ICONS: Record<string, LucideIcon> = {
  soup: Soup,
  moon: Moon,
  sun: Sun,
  pill: Pill,
  heart: Heart,
  "heart-handshake": HeartHandshake,
  "moon-star": MoonStar,
  flower: Flower,
  "flower-2": Flower2,
  "chef-hat": ChefHat,
  baby: Baby,
  droplets: Droplets,
  sunrise: Sunrise,
  footprints: Footprints,
  armchair: Armchair,
  lightbulb: Lightbulb,
  sprout: Sprout,
  "message-circle": MessageCircle,
};

export function KudosIcon({ name, size = 20, className = "" }: { name: string; size?: number; className?: string }) {
  const Icon = KUDOS_ICONS[name] ?? Heart;
  return <Icon size={size} className={className} aria-hidden />;
}
