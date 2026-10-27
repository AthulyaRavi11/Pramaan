export default function PramaanMark({ size = 32, title, className, style }) {
  return (
    <img
      src="/logo.png"
      alt={title || "Pramaan Logo"}
      width={size}
      height={size}
      className={className}
      style={{
        display: 'inline-block',
        verticalAlign: 'middle',
        borderRadius: size > 24 ? 6 : 4,
        objectFit: 'contain',
        ...style
      }}
    />
  )
}
