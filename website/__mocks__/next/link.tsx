import type { AnchorHTMLAttributes, ReactNode } from "react";

// Manual Jest mock for next/link, adjacent to node_modules -- Jest applies this
// automatically to every `import Link from "next/link"` in the test suite, with
// zero effect on the real `next build`/production bundle (which always imports the
// real next/link). Needed because next/link's real App Router implementation reads
// an AppRouterContext that plain @testing-library/react renders don't provide,
// which can throw in some Next 14 versions; rendering a plain anchor here is
// functionally equivalent for what these tests check (href, text, data-* attrs,
// className).
interface MockLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
  children?: ReactNode;
}

export default function Link({ href, children, ...rest }: MockLinkProps) {
  return (
    <a href={href} {...rest}>
      {children}
    </a>
  );
}
