// Silhouette and organ coordinates extracted and adapted from gganatogram
// (https://github.com/jespermaag/gganatogram), dataset
// data-raw/homo_sapiens.{male,female}_coords.tsv - Copyright Jesper Maag,
// released under the GPL-2 license. See THIRD_PARTY_NOTICES.md at the
// project root for full license and attribution details.
import raw from './anatomy.json';
import type { AnatomyData, Sex } from '../types/anatomy';

const dataset = raw as unknown as Record<Sex, AnatomyData>;

/** Returns the full silhouette + organ dataset for the given {@link Sex}. */
export function getAnatomy(sex: Sex): AnatomyData {
  return dataset[sex];
}
