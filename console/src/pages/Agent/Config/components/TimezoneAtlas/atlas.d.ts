declare module "world-atlas/land-110m.json" {
  const topology: import("topojson-specification").Topology<{
    land: import("topojson-specification").GeometryCollection;
  }>;
  export default topology;
}
