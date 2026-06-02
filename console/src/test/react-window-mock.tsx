import React from "react";

export const FixedSizeList = ({
  children,
  itemData,
  itemCount,
}: {
  children: React.ReactNode;
  itemData: any;
  itemCount: number;
}) => {
  const Row = children as unknown as React.ComponentType<any>;
  return (
    <>
      {Array.from({ length: itemCount }, (_, i) => (
        <Row key={i} index={i} style={{}} data={itemData} />
      ))}
    </>
  );
};

export default { FixedSizeList };
